"""Review and publish a whitelist of public website values, never raw ledgers."""
import hashlib
import json
import os
import re
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from portal_sync import signed_request, SyncError


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)


def _decimal(value, places, maximum, positive=False):
    value = str(value or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1," + str(places) + r"})?" if places else r"\d+", value):
        raise ValueError("Use numbers without thousands separators.")
    number = Decimal(value)
    if number > Decimal(str(maximum)) or (positive and number <= 0):
        raise ValueError("Public amount is outside the allowed range.")
    return format(number.normalize(), "f")


def _minimum(config):
    return _decimal(config.get("min_co2_per_pi", 20), 3, 1000000, True)


def _payload(draft, minimum):
    fields = ("contributions_pi", "estimated_co2_kg", "trees", "as_of")
    impact = None
    if any(str(draft.get(k) or "").strip() for k in fields):
        date = str(draft.get("as_of") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("Enter the date through which all records have been checked.")
        checked = datetime.strptime(date, "%Y-%m-%d").date()
        if checked > datetime.now(UTC).date():
            raise ValueError("The review date cannot be in the future.")
        impact = {"contributionsPi": _decimal(draft.get("contributions_pi"), 7, 1e12),
                  "estimatedCo2Kg": _decimal(draft.get("estimated_co2_kg"), 3, 1e15),
                  "trees": _decimal(draft["trees"], 0, 1e12) if draft.get("trees") else None,
                  "asOf": date}
    payload = {"schema": "tpf_website_summary_v1", "environment": "mainnet",
               "minimumCo2KgPerPi": minimum, "impact": impact}
    revision = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload, revision


def screen(path, config, environment, origin, secret):
    state = _read(path); published = None; error = None
    try:
        published = signed_request(origin, secret, "GET", "/api/ops/website-data")
    except (SyncError, OSError, ValueError) as exc:
        error = "Cannot read the online summary. Publishing is disabled until the connection works. " + str(exc)
    draft = state.get("draft", {})
    if not draft and published and published.get("impact"):
        impact = published["impact"]
        draft = {"contributions_pi": impact["contributionsPi"], "estimated_co2_kg": impact["estimatedCo2Kg"],
                 "trees": impact.get("trees") or "", "as_of": impact["asOf"]}
    try:
        minimum = _minimum(config)
        payload, revision = _payload(draft, minimum)
        review = {**payload, "revision": revision} if state.get("reviewed_revision") == revision else None
    except ValueError as exc:
        minimum = config.get("min_co2_per_pi", 20); review = None; error = str(exc)
    if environment != "mainnet":
        error = "Website publication is disabled in test or sandbox mode."
    return {"origin": origin, "environment": environment, "minimum": minimum, "published": published,
            "draft": draft, "review": review, "error": error,
            "can_publish": environment == "mainnet" and not error and review is not None}


def handle_form(form, path, config, environment, origin, secret):
    state = _read(path)
    try:
        if environment != "mainnet":
            raise ValueError("Test and sandbox data cannot be published.")
        if form.get("action") == "review":
            draft = {k: str(form.get(k) or "").strip() for k in ("contributions_pi", "estimated_co2_kg", "trees", "as_of", "review_note")}
            draft["review_note"] = draft["review_note"][:2000]
            state.update(draft=draft, reviewed_revision=None)
            _write(path, state)
            payload, revision = _payload(draft, _minimum(config))
            current = signed_request(origin, secret, "GET", "/api/ops/website-data")
            if current.get("impact") and payload["impact"] is None:
                raise ValueError("Keep the existing totals in the review; publishing an empty draft would remove them.")
            state.update(draft=draft, reviewed_revision=revision, expected_revision=current.get("revision"))
            _write(path, state)
            return {"ok": True, "message": "Draft saved. Check the public values below, then publish when ready."}
        if form.get("action") != "publish" or form.get("confirmed") != "yes":
            raise ValueError("Review and confirm the public values before publishing.")
        payload, revision = _payload(state.get("draft", {}), _minimum(config))
        if revision != state.get("reviewed_revision") or revision != form.get("draft_revision"):
            raise ValueError("The settings or draft changed. Save and review the draft again.")
        payload["expectedRevision"] = state.get("expected_revision")
        result = signed_request(origin, secret, "POST", "/api/ops/website-data", payload)
        state.update(last_published=result, reviewed_revision=None)
        _write(path, state)
        return {"ok": True, "message": "Website data published. Public pages now use this summary."}
    except (ValueError, SyncError, OSError) as exc:
        return {"ok": False, "message": str(exc)}
