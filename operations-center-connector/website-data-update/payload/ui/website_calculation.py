"""Calculate planting totals from mainnet proof records. Never count allocations."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


def number(value, integer=False):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n <= 0 or (integer and n != n.to_integral_value()):
            raise ValueError('Planting amounts must be positive numbers.')
        if n > Decimal('1000000000000') or n.as_tuple().exponent < -3:
            raise ValueError('Planting amount exceeds supported precision or range.')
        return n
    except InvalidOperation:
        raise ValueError('Missing or invalid planting amount.')


def refs(certificates):
    result = set()
    for c in certificates:
        if not isinstance(c, dict):
            continue
        # A production certificate is required; IDs alone cannot prove mainnet.
        for key in ('certificate_url', 'public_proof_url', 'tree_url'):
            u = urlsplit(str(c.get(key) or ''))
            if u.scheme != 'https' or u.netloc != 'tree-nation.com' or u.query or u.fragment:
                continue
            m = re.fullmatch(r'/(?:certificate|es/certificado)/([a-fA-F0-9]+)', u.path)
            t = re.fullmatch(r'/trees/(\d+)/view', u.path)
            if m: result.add('certificate:' + m[1].lower())
            if t: result.add('tree:' + t[1])
        if any(str(c.get(k) or '').startswith('https://tree-nation.com/') for k in ('certificate_url', 'tree_url', 'public_proof_url')) and str(c.get('tree_id') or c.get('id') or '').isdigit():
            result.add('tree:' + str(c.get('tree_id') or c.get('id')))
    return result


def _calculate(root):
    root = Path(root)
    entries, issues, ignored = [], [], []
    def read(path):
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict): raise ValueError('Expected a record object')
            return value
        except (OSError, ValueError) as exc:
            issues.append(str(path.relative_to(root)) + ': unreadable record'); return None
    def add(source, qty, co2, certificates, payment=None, date=None):
        try:
            q, c = number(qty, True), number(co2)
            identities = refs(certificates)
            if not identities: raise ValueError('Missing production planting proof.')
            if payment is not None:
                if not str(payment).isdigit(): raise ValueError('Invalid Tree-Nation payment reference.')
                identities.add('payment:' + str(payment))
            entries.append({'source': source, 'trees': int(q), 'co2': format(c.normalize(), 'f'),
                            'identities': sorted(identities), 'date': str(date or '')[:10]})
        except (ValueError, TypeError) as exc:
            issues.append(source + ': ' + str(exc))
    history_path = root / 'project-intelligence/history/historical_ledger_import.json'
    if history_path.exists():
        history = read(history_path)
        for i, row in enumerate((history or {}).get('records', [])):
            for j, a in enumerate(row.get('annotations', [])):
                impact, links = a.get('impact') or {}, a.get('links') or {}
                if not impact.get('trees') and not impact.get('co2_kg'): continue
                add('historical/' + str(i) + '/' + str(j), impact.get('trees'), impact.get('co2_kg'),
                    [{'certificate_url': links.get('certificate'), 'tree_url': links.get('tree')}])
    for folder in ('plantings', 'co2-pool/pools'):
        for path in sorted((root / folder).glob('*.json')):
            d = read(path)
            if d: add(str(path.relative_to(root)), d.get('quantity'), d.get('total_co2_kg'),
                      d.get('certificates') or [], d.get('payment_id'), d.get('created_at'))
    for path in sorted((root / 'project-intelligence/trees').glob('*.json')):
        d = read(path)
        if not d: continue
        try: co2 = number(d.get('quantity'), True) * number(d.get('species_life_time_co2_kg'))
        except ValueError: co2 = None
        add(str(path.relative_to(root)), d.get('quantity'), co2, [d], d.get('payment_id'), d.get('created_at'))
    for path in sorted((root / 'tree-nation').glob('*.json')):
        d = read(path)
        if not d or 'response' not in d: continue
        response = d.get('response') or {}; data = response.get('json') or {}
        if data.get('status') != 'ok' or not 200 <= int(response.get('status_code') or 0) < 300:
            ignored.append(str(path.relative_to(root))); continue
        trees = data.get('trees') or []
        payload = (d.get('request') or {}).get('payload') or {}
        # Current API purchases use one grouped certificate, or one per tree.
        try: qty = number(payload.get('quantity'), True)
        except ValueError: qty = None
        if len(trees) == 1:
            try: co2 = qty * number(trees[0].get('species_life_time_CO2'))
            except (ValueError, TypeError): co2 = None
        elif qty is not None and len(trees) == qty:
            try: co2 = sum(number(t.get('species_life_time_CO2')) for t in trees)
            except ValueError: co2 = None
        else: co2 = None
        add(str(path.relative_to(root)), qty, co2, trees, data.get('payment_id'), d.get('created_at') or d.get('tested_at'))
    # Merge transitive aliases: certificate, tree ID and payment ID identify one purchase.
    groups = []
    for entry in entries:
        identity = set(entry['identities']); matches = [g for g in groups if identity & g['identities']]
        for g in matches:
            identity |= g['identities']; groups.remove(g)
        members = [entry] + [e for g in matches for e in g['members']]
        groups.append({'identities': identity, 'members': members})
    rows = []
    for g in groups:
        members = g['members']; values = {(e['trees'], e['co2']) for e in members}
        if len(values) != 1:
            issues.append('Conflicting quantities or CO₂: ' + ', '.join(e['source'] for e in members)); continue
        first = members[0]
        rows.append({'trees': first['trees'], 'co2': first['co2'], 'sources': [e['source'] for e in members],
                     'proofs': sorted(g['identities']), 'date': max(e['date'] for e in members)})
    rows.sort(key=lambda r: r['proofs'])
    if not rows: issues.append('No production planting records found.')
    total = sum((Decimal(r['co2']) for r in rows), Decimal(0))
    canonical = [{'trees': r['trees'], 'co2': r['co2'], 'proofs': r['proofs']} for r in rows]
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return {'rows': rows, 'issues': issues, 'ignored': ignored, 'trees': sum(r['trees'] for r in rows),
            'co2': format(total.normalize(), 'f'), 'fingerprint': fingerprint,
            'duplicates': len(entries) - len(groups), 'source_count': len(entries)}


def calculate(root):
    try:
        return _calculate(root)
    except (TypeError, ValueError, KeyError, AttributeError, InvalidOperation, OSError):
        return {'rows': [], 'issues': ['A planting record has an unsupported structure. Check the source records.'],
                'ignored': [], 'trees': 0, 'co2': '0', 'fingerprint': None, 'duplicates': 0, 'source_count': 0}
