"""Automatic public summary sync; all evidence and diagnostics stay local."""
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from portal_sync import signed_request, SyncError
from website_calculation import calculate

ENDPOINT = '/api/website-data/admin'
_mutex = threading.RLock()
_started = False

def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict): raise ValueError('Invalid sync state')
        return data
    except FileNotFoundError: return {}

def _write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as h:
        json.dump(data, h, ensure_ascii=False, indent=2); h.flush(); os.fsync(h.fileno())
    os.replace(tmp, path)

@contextmanager
def _locked(path):
    with _mutex:
        lock = Path(path).with_suffix('.lock'); lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a+b') as h:
            if os.name == 'nt':
                import msvcrt
                if h.tell() == 0: h.write(b'0'); h.flush()
                h.seek(0); msvcrt.locking(h.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try: yield
            finally:
                if os.name == 'nt':
                    h.seek(0); msvcrt.locking(h.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(h, fcntl.LOCK_UN)

def _minimum(config):
    n = Decimal(str(config.get('min_co2_per_pi', 20)))
    if not n.is_finite() or n <= 0 or n > 1000000 or n.as_tuple().exponent < -3:
        raise ValueError('Invalid public minimum in Settings.')
    return format(n.normalize(), 'f')

def _online(origin, secret):
    online = signed_request(origin, secret, 'GET', ENDPOINT)
    if not isinstance(online, dict) or online.get('schema') != 'tpf_website_summary_v1':
        raise ValueError('The website returned an invalid summary. Sync will retry.')
    return online

def _same(online, payload):
    return isinstance(online, dict) and all(online.get(k) == payload.get(k) for k in ('schema', 'minimumCo2KgPerPi', 'impact'))

def _snapshot(calc):
    return [r['proofs'] for r in calc['rows']]

def _missing(state, calc):
    current = {p for r in calc['rows'] for p in r['proofs']}
    return any(not current.intersection(proofs) for proofs in state.get('accepted_proofs', []))

def tick(path, root, config, environment, origin, secret):
    """One retry-safe cycle. Only enabled, validated mainnet summaries can leave disk."""
    if environment != 'mainnet': return
    try:
        with _locked(path):
            state = _read(path)
            if not state.get('automatic_enabled'): return
            now = datetime.now(UTC).isoformat()
            state['last_attempt'] = now
            try:
                calc = calculate(root)
                if calc['issues']: raise ValueError('Records need attention: ' + '; '.join(calc['issues']))
                if _missing(state, calc): raise ValueError('A previously counted planting is missing. Restore its record before syncing.')
                minimum = _minimum(config)
                local_key = hashlib.sha256((calc['fingerprint'] + ':' + minimum).encode()).hexdigest()
                checked = state.get('calculated_on') if local_key == state.get('calculation_key') else now[:10]
                payload = {'schema': 'tpf_website_summary_v1', 'environment': 'mainnet',
                           'minimumCo2KgPerPi': minimum,
                           'impact': {'estimatedCo2Kg': calc['co2'], 'trees': str(calc['trees']), 'asOf': checked}}
                state.update(calculation_key=local_key, calculated_on=checked)
                online = _online(origin, secret)
                if not _same(online, payload):
                    if online.get('revision') != state.get('accepted_online_revision'):
                        raise ValueError('The online summary was changed elsewhere. Check the difference before syncing.')
                    payload['expectedRevision'] = online.get('revision')
                    online = signed_request(origin, secret, 'POST', ENDPOINT, payload)
                    if not _same(online, payload): raise ValueError('Online response does not match the calculated totals.')
                state.update(last_success=now, last_published=online, status='current', error=None,
                             accepted_online_revision=online.get('revision'), accepted_proofs=_snapshot(calc))
            except (ValueError, OSError, SyncError, TypeError, ArithmeticError) as exc:
                state.update(status='attention', error=str(exc))
            _write(path, state)
    except (OSError, ValueError):
        # Another Admin process owns the cycle, or disk/state is unavailable.
        # The screen checks freshness and will never show a false green result.
        return

def screen(path, config, environment, origin, secret, root=None):
    root = Path(root) if root else Path(path).parent.parent
    try: state = _read(path)
    except (ValueError, OSError): state = {'error': 'Sync state cannot be read. Restore it from backup.', 'status': 'attention'}
    calc = calculate(root)
    try: minimum = _minimum(config)
    except (ValueError, ArithmeticError) as exc:
        minimum = 'Invalid'; calc['issues'].append(str(exc))
    fresh = False
    if state.get('last_success'):
        try: fresh = (datetime.now(UTC) - datetime.fromisoformat(state['last_success'])).total_seconds() < 180
        except ValueError: pass
    published = state.get('last_published') or {}
    current = (fresh and not state.get('error') and not calc['issues'] and not _missing(state, calc)
               and published.get('minimumCo2KgPerPi') == minimum
               and (published.get('impact') or {}).get('trees') == str(calc['trees'])
               and (published.get('impact') or {}).get('estimatedCo2Kg') == calc['co2'])
    label = 'Up to date' if current else 'Waiting for first check' if not state.get('automatic_enabled') else 'Update pending'
    if calc['issues'] or state.get('error') or _missing(state, calc): label = 'Needs attention'
    if environment != 'mainnet': label = 'Disabled in test mode'; current = False
    return {'origin': origin, 'environment': environment, 'minimum': minimum, 'calculation': calc,
            'state': state, 'published': published, 'current': current, 'label': label,
            'can_enable': environment == 'mainnet' and not calc['issues'] and not state.get('automatic_enabled'),
            'can_reconcile': environment == 'mainnet' and not calc['issues'] and state.get('automatic_enabled') and ('elsewhere' in str(state.get('error') or '') or _missing(state, calc))}

def handle_form(form, path, config, environment, origin, secret, root=None):
    root = Path(root) if root else Path(path).parent.parent
    try:
        if environment != 'mainnet': raise ValueError('Test records cannot be synced to the website.')
        with _locked(path):
            state = _read(path)
            if form.get('action') not in ('enable', 'reconcile') or form.get('confirmed') != 'yes':
                raise ValueError('Check the calculated records once before enabling automatic updates.')
            if state.get('automatic_enabled') and form.get('action') != 'reconcile': raise ValueError('Automatic updates are already enabled.')
            if form.get('action') == 'reconcile' and not str(form.get('reason') or '').strip():
                raise ValueError('Record why this correction was checked before resuming.')
            calc = calculate(root)
            if calc['issues']: raise ValueError('Resolve the listed record issues first.')
            if calc['fingerprint'] != form.get('fingerprint'):
                raise ValueError('Records changed during the first check. Reload and check the calculation.')
            online = _online(origin, secret)
            if form.get('action') == 'reconcile':
                audit = state.setdefault('corrections', [])
                audit.append({'at': datetime.now(UTC).isoformat(), 'reason': str(form.get('reason'))[:2000],
                              'fingerprint': calc['fingerprint']})
            state.update(automatic_enabled=True, enabled_at=state.get('enabled_at') or datetime.now(UTC).isoformat(),
                         accepted_proofs=_snapshot(calc), accepted_online_revision=online.get('revision'))
            _write(path, state)
        tick(path, root, config, environment, origin, secret)
        return {'ok': True, 'message': 'Automatic updates enabled. New valid planting records and minimum changes sync without a publish button.'}
    except (ValueError, SyncError, OSError) as exc:
        return {'ok': False, 'message': str(exc)}

def start_worker(provider):
    """Start once per process. Work continues while Operations Center is running."""
    global _started
    with _mutex:
        if _started: return
        _started = True
    def run():
        while True:
            try:
                path, root, config, environment, origin, secret = provider()
                tick(path, root, config, environment, origin, secret)
            except Exception:
                # Failed settings/reads retry; the visible status expires after 3 minutes.
                pass
            threading.Event().wait(60)
    threading.Thread(target=run, name='tpf-website-sync', daemon=True).start()
