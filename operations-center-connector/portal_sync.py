"""Small connector for TPF Operations Center; no mainnet files are modified on import."""

import hashlib
import hmac
import base64
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path


class SyncError(Exception):
    pass


def build_payload(partner, pools, assets_dir, make_export, connections=None):
    """Use the Admin's existing proof-checked export, never its balance fields."""
    if partner.get("schema") != "tpf_partner_v1":
        raise SyncError("Invalid local partner")
    setup = None
    if pools:
        exported = make_export(partner, pools, assets_dir)
        with zipfile.ZipFile(BytesIO(exported.getvalue())) as archive:
            path = "partner-pages/{}/setup.json".format(partner["id"])
            setup = json.loads(archive.read(path))
    # Keep profile keys needed by the portal. No internal notes or offer prices.
    fields = ("schema", "id", "name", "section_title", "tagline", "intro", "colors", "status")
    profile = {key: partner.get(key) for key in fields}
    logo = None
    logo_name = partner.get("logo_file") or ""
    if logo_name:
        if logo_name not in (partner["id"] + ext for ext in (".png", ".jpg", ".webp")):
            raise SyncError("Invalid partner logo name")
        content = (Path(assets_dir) / logo_name).read_bytes()
        if not content or len(content) > 2_000_000:
            raise SyncError("Partner logo must be under 2 MB")
        kind = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[Path(logo_name).suffix]
        logo = {"contentType": kind, "data": base64.b64encode(content).decode("ascii")}
    connections = connections or []
    pool_ids = {pool["pool_id"] for pool in pools}
    if any(item.get("poolId") not in pool_ids for item in connections):
        raise SyncError("A connected request needs its verified pool in this publication")
    raw = json.dumps({"profile": profile, "setup": setup, "logo": logo,
                      "connections": connections}, sort_keys=True,
                     ensure_ascii=False, separators=(",", ":"))
    revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {"profile": profile, "setup": setup, "logo": logo,
            "connections": connections, "revision": revision}


def signed_request(base_url, secret, method, path, payload=None, opener=None):
    base = urllib.parse.urlsplit(base_url)
    if base.scheme != "https" or not base.netloc or base.path not in ("", "/"):
        raise SyncError("Use an HTTPS site origin")
    if len(secret) < 32:
        raise SyncError("Configure a long Operations Center sync secret")
    body = "" if payload is None else json.dumps(payload, ensure_ascii=False,
        separators=(",", ":"))
    timestamp = str(int(time.time()))
    signed = "{}\n{}\n{}\n{}".format(timestamp, method, path, body)
    signature = hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
    request = urllib.request.Request(base_url.rstrip("/") + path,
        data=body.encode("utf-8") if method == "POST" else None,
        method=method, headers={"X-TPF-Timestamp": timestamp,
            "X-TPF-Signature": signature, "Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=20) as response:
            return json.load(response)
    except Exception as exc:
        raise SyncError("Portal sync failed: {}".format(exc)) from exc


def publish_partner(base_url, secret, partner, pools, assets_dir, make_export, opener=None,
                    connections=None):
    payload = build_payload(partner, pools, assets_dir, make_export, connections)
    return signed_request(base_url, secret, "POST", "/api/ops/publish", payload, opener)


def send_offer(base_url, secret, partner_id, request_id, offer, opener=None):
    """Send only the partner-facing saved snapshot. Keep internal cost/pricing local."""
    if offer.get("schema") != "tpf_partner_offer_v1" or offer.get("status") != "ready":
        raise SyncError("Choose a ready saved offer")
    fields = ("key", "project", "species", "common_name", "project_note",
              "trees", "co2_kg", "partner_price_pi")
    public = {"schema": offer["schema"], "id": offer["id"], "name": offer.get("name", ""),
              "status": "ready", "search": {"basis": offer.get("search", {}).get("basis")},
              "choices": [{key: choice.get(key) for key in fields} for choice in offer["choices"]]}
    revision = hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return signed_request(base_url, secret, "POST", "/api/ops/offer", {
        "partnerId": partner_id, "requestId": request_id, "offer": public, "revision": revision
    }, opener)


def new_invitation(base_url, secret, partner_id, opener=None):
    return signed_request(base_url, secret, "POST", "/api/ops/invite",
                          {"partnerId": partner_id}, opener)


def pull_events(base_url, secret, inbox_dir, opener=None):
    """Save every event locally before advancing the cursor; retries replace same IDs."""
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    cursor_path = inbox / "cursor.txt"
    after = int(cursor_path.read_text(encoding="ascii")) if cursor_path.exists() else 0
    result = signed_request(base_url, secret, "GET", "/api/ops/events?after={}".format(after), opener=opener)
    events = result.get("events")
    if not isinstance(events, list):
        raise SyncError("Invalid portal event response")
    for event in events:
        event_id = int(event["id"])
        if event_id <= after:
            raise SyncError("Portal event order changed")
        destination = inbox / ("{:016d}.json".format(event_id))
        _atomic_write(destination, json.dumps(event, ensure_ascii=False, indent=2))
        after = event_id
    _atomic_write(cursor_path, str(after))
    return len(events), after


def _atomic_write(destination, value):
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
