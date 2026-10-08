from flask import Flask, render_template, request, redirect, url_for, jsonify
import subprocess
import requests
import json
import re
import os
import time
import shutil
from datetime import datetime, UTC
from pathlib import Path
from dotenv import load_dotenv
from markupsafe import Markup, escape
from urllib.parse import quote
from uuid import uuid4
import tempfile
import threading
from decimal import Decimal, InvalidOperation
from itsdangerous import URLSafeSerializer, BadData
from pricing_engine import catalog_choices, budget_choices, number, range_preview, sort_choices

app = Flask(__name__)


def active_environment_config():
    """Current Operations Center environment.
    v1: display-only safety banner. Data movement comes in the next step.
    """
    config = load_json(CONFIG_FILE, {}) or {}
    env = str(config.get("active_environment", "mainnet")).strip().lower()
    if env not in ["mainnet", "testnet", "sandbox"]:
        env = "mainnet"

    if env == "mainnet":
        return {
            "name": "MAINNET",
            "key": "mainnet",
            "class": "environment-mainnet",
            "label": "🟢 MAINNET MODE",
            "message": "Real wallet / real historical ledger. Treat actions as production-sensitive."
        }

    return {
        "name": env.upper(),
        "key": env,
        "class": "environment-testnet",
        "label": "🧪 TEST / SANDBOX MODE",
        "message": "Sandbox data only. Do not treat records as public accounting."
    }


@app.context_processor
def inject_environment_banner():
    return {"active_environment": active_environment_config(),
            "portal_sync_ready": len(os.getenv("TPF_OPS_SYNC_SECRET", "")) >= 32}

UI_DIR = Path(__file__).resolve().parent
ROOT_DIR = UI_DIR.parent
DATA_DIR = ROOT_DIR / "data"
ACTIVE_ENV = "mainnet"
DATA_ROOT = DATA_DIR / ACTIVE_ENV
SCRIPTS_DIR = ROOT_DIR / "scripts"
CONFIG_FILE = ROOT_DIR / "config.local.json"
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)

PENDING_DIR = DATA_ROOT / "donations" / "pending"
WORKING_DONATION_FILENAME = "donation_test_001.json"
# Internal compatibility bridge for older backend scripts.
# Do not show this file as a real pending donation in the UI.
WORKING_DONATION_FILE = PENDING_DIR / WORKING_DONATION_FILENAME
PROCESSED_INPUT_DIR = DATA_ROOT / "donations" / "processed_input"
CATALOG_FILE = DATA_ROOT / "tree-nation" / "catalog.json"
FULL_CATALOG_FILE = DATA_ROOT / "tree-nation" / "full_catalog.json"



def now_iso():
    return datetime.now(UTC).isoformat()

def load_json(path, default=None):
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json_files(folder):
    items = []

    if not folder.exists():
        return items

    for file_path in sorted(folder.glob("*.json"), reverse=True):
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                items.append({
                    "file": file_path.name,
                    "path": str(file_path),
                    "path_obj": file_path,
                    "modified": file_path.stat().st_mtime,
                    "data": json.load(f)
                })
        except Exception as e:
            items.append({
                "file": file_path.name,
                "path": str(file_path),
                "path_obj": file_path,
                "modified": file_path.stat().st_mtime if file_path.exists() else 0,
                "error": str(e),
                "data": {}
            })

    return items


def route_label(route):
    labels = {
        "co2_pool": "Covered by Shared CO₂ Pool",
        "direct_planting_suggestions": "Direct planting options created",
    }
    return labels.get(route, route or "—")


def status_label(status):
    labels = {
        "completed": "✅ Completed",
        "blocked_needs_new_pool": "⚠️ Needs new pool",
        "blocked_duplicate": "⛔ Duplicate blocked",
        "blocked_wrong_route": "⚠️ Wrong route",
        "blocked": "⚠️ Blocked",
        "error": "❌ Error",
    }
    return labels.get(status, status or "—")


def next_step_for_process(status):
    if status == "completed":
        return "Nothing to do"
    if status == "blocked_needs_new_pool":
        return "Create a new CO₂ pool, then process this donation again"
    if status == "blocked_duplicate":
        return "Do not process again unless you intentionally reset this test"
    if status == "blocked_wrong_route":
        return "Use direct planting flow instead"
    if status == "error":
        return "Check full log / script error"
    return "Review details"


def load_processed_items():
    processed_dir = DATA_ROOT / "donations" / "processed"
    return load_json_files(processed_dir)


def completed_donation_ids_from_processed():
    completed = set()

    for item in load_processed_items():
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        if data.get("workflow_status") != "completed":
            continue

        donation = data.get("donation", {})
        donation_id = donation.get("donation_id")

        if donation_id:
            completed.add(donation_id)

    return completed


def has_donation_completed(donation_id):
    return donation_id in completed_donation_ids_from_processed()


def pending_donation_preview_for_file(item):
    config = load_json(CONFIG_FILE, {})
    donation = item.get("data", {})

    if not donation or not isinstance(donation, dict):
        return None

    donation_id = donation.get("donation_id", "—")
    already_completed = has_donation_completed(donation_id)

    amount_pi = donation.get("amount_pi", 0)
    pool_limit = config.get("co2_pool_auto_limit_pi", 5)
    min_co2_per_pi = config.get("min_co2_per_pi", 30)
    pi_value = config.get("pi_value", 0)
    currency = config.get("currency", "EUR")

    required_co2 = amount_pi * min_co2_per_pi
    budget = amount_pi * pi_value

    if amount_pi <= pool_limit:
        expected_route = "Shared CO₂ Pool"
        route_note = "This should be covered from an existing CO₂ pool if one pool has enough remaining CO₂."
    else:
        expected_route = "Direct Planting"
        route_note = "This should create planting options for manual project/species selection."

    if already_completed:
        route_note = "This donation ID already has a completed process. Archive this pending input before continuing."

    return {
        "file": item.get("file"),
        "path": item.get("path"),
        "modified": item.get("modified"),
        "donation_id": donation_id,
        "donor": donation.get("donor", "—"),
        "tx_hash": donation.get("tx_hash", "—"),
        "from_address": donation.get("from_address", donation.get("sender_address", donation.get("wallet_from", ""))),
        "amount_pi": amount_pi,
        "required_co2": required_co2,
        "budget": round(budget, 2),
        "currency": currency,
        "expected_route": expected_route,
        "route_note": route_note,
        "pool_limit": pool_limit,
        "already_completed": already_completed
    }


def pending_donation_queue():
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    items = load_json_files(PENDING_DIR)
    queue = []

    for item in items:
        # donation_test_001.json is an internal compatibility copy for older backend scripts.
        # Showing it in the UI creates duplicate/blank donation cards and identity confusion.
        if item.get("file") == WORKING_DONATION_FILENAME:
            continue

        if item.get("error"):
            queue.append({
                "file": item.get("file"),
                "modified": item.get("modified", 0),
                "donation_id": "Unreadable pending file",
                "donor": "—",
                "tx_hash": "—",
                "amount_pi": "—",
                "required_co2": "—",
                "budget": "—",
                "currency": "—",
                "expected_route": "Needs file check",
                "route_note": item.get("error"),
                "pool_limit": 5,
                "already_completed": False,
                "error": item.get("error")
            })
            continue

        preview = pending_donation_preview_for_file(item)

        if preview:
            queue.append(preview)

    queue.sort(key=lambda x: x.get("modified", 0), reverse=True)
    return queue


def archive_pending_files_for_donation(donation_id):
    if not donation_id:
        return []

    PROCESSED_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    moved = []

    for item in load_json_files(PENDING_DIR):
        # Do not archive the internal compatibility copy as if it was user input.
        # It is recreated when processing a selected pending donation.
        if item.get("file") == WORKING_DONATION_FILENAME:
            continue

        data = item.get("data", {})

        if not isinstance(data, dict):
            continue

        if data.get("donation_id") != donation_id:
            continue

        src = item["path_obj"]
        timestamp = int(time.time())
        target = PROCESSED_INPUT_DIR / f"processed_input_{donation_id}_{timestamp}_{src.name}"

        shutil.move(str(src), str(target))
        moved.append(str(target))

    return moved


def archive_completed_pending_inputs():
    moved = []
    completed_ids = completed_donation_ids_from_processed()

    for donation_id in completed_ids:
        moved.extend(archive_pending_files_for_donation(donation_id))

    return moved


def normalize_options(raw_options):
    normalized = []

    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, dict):
                option_copy = dict(option)
                option_copy.setdefault("view_name", "options")
                normalized.append(option_copy)

    elif isinstance(raw_options, dict):
        for view_name, view_options in raw_options.items():
            if isinstance(view_options, list):
                for option in view_options:
                    if isinstance(option, dict):
                        option_copy = dict(option)
                        option_copy.setdefault("view_name", view_name)
                        normalized.append(option_copy)
            elif isinstance(view_options, dict):
                option_copy = dict(view_options)
                option_copy.setdefault("view_name", view_name)
                normalized.append(option_copy)

    return normalized


def prepare_suggestion_items():
    raw_items = load_json_files(DATA_ROOT / "suggestions")
    prepared = []

    for item in raw_items:
        data = item.get("data", {})

        if not isinstance(data, dict):
            item["error"] = "Suggestion JSON root is not an object."
            item["options_flat"] = []
            prepared.append(item)
            continue

        raw_options = (
            data.get("options")
            or data.get("suggestions")
            or data.get("direct_planting_options")
            or []
        )

        item["options_flat"] = normalize_options(raw_options)
        prepared.append(item)

    return prepared


def selected_option_summary(decision):
    selected = decision.get("selected_option", {}) if isinstance(decision, dict) else {}

    return {
        "project": (
            selected.get("project_name")
            or selected.get("project_title")
            or selected.get("project", "Unknown project")
        ),
        "species": (
            selected.get("species_name")
            or selected.get("species_title")
            or selected.get("species", "Unknown species")
        ),
        "project_id": selected.get("project_id", "—"),
        "species_id": selected.get("species_id", "—"),
        "total_co2": selected.get("total_co2", selected.get("total_co2_kg", "—")),
        "total_cost": selected.get("total_cost", selected.get("total_cost_eur", "—")),
        "quantity": selected.get("quantity", selected.get("max_qty", selected.get("qty", "—"))),
    }



def build_direct_tree_nation_message(decision):
    """Create the editable public Tree-Nation message for a direct planting.

    The Tree-Nation post already displays project/species/certificate details,
    so this message stays warm and human. Technical planting data remains in
    the Operations Center record and Tree-Nation certificate.
    """
    existing = (decision.get("tree_nation_message") or "").strip()
    if existing:
        return existing

    donation = decision.get("donation", {}) if isinstance(decision.get("donation", {}), dict) else {}
    identity = decision.get("identity", {}) if isinstance(decision.get("identity", {}), dict) else {}

    display_name = (
        identity.get("display_name")
        or donation.get("display_name")
        or donation.get("public_display_name")
        or donation.get("donor")
        or "Arboris"
    )
    display_name = str(display_name).strip() or "Arboris"

    # Keep the public message friendly. For anonymous/Arboris records, avoid
    # pretending we know a personal username.
    lines = ["The Pioneer Forest 🌱", ""]

    if display_name.lower() == "arboris":
        lines.append("A generous Pioneer contribution has helped turn Pi support into real trees and lasting CO₂ balance.")
        lines.append("Thank you for helping The Pioneer Forest grow, one rooted step at a time.")
    else:
        lines.append(f"Thank you, {display_name} 💚")
        lines.append("Your Pi support has helped turn a simple contribution into real trees and lasting CO₂ balance.")
        lines.append("Together, we keep The Pioneer Forest growing, one rooted step at a time.")

    note_lines = []
    if identity.get("include_wallet_note_in_message") or donation.get("include_wallet_note_in_message"):
        note = identity.get("wallet_note") or donation.get("wallet_note") or donation.get("memo_raw") or ""
        note = str(note).strip()
        if note:
            note_lines.append(note)

    if (
        identity.get("include_message_note_in_message")
        or identity.get("include_public_note_in_message")
        or donation.get("include_message_note_in_message")
        or donation.get("include_public_note_in_message")
    ):
        note = identity.get("message_note") or identity.get("public_note") or donation.get("message_note") or donation.get("public_note") or ""
        note = str(note).strip()
        if note:
            note_lines.append(note)

    if note_lines:
        lines.append("")
        if len(note_lines) == 1:
            lines.append(f"Message: {note_lines[0]}")
        else:
            lines.append("Messages:")
            for note in note_lines:
                lines.append(f"- {note}")

    exception = decision.get("donor_choice_exception", {}) if isinstance(decision.get("donor_choice_exception", {}), dict) else {}
    if exception.get("approved"):
        reason = str(exception.get("reason") or "Donor-requested tree/species").strip()
        lines.append("")
        lines.append(f"Planting preference: {reason}. This donor-directed planting prioritizes the requested tree/species over TPF's standard CO₂-per-Pi target.")

    lines.extend(["", "#ThePioneerForest"])
    return "\n".join(lines)


def enrich_decision_with_donation_identity(decision):
    """Attach donation + current editable identity to a decision dict."""
    decision = dict(decision or {})
    donation_id = decision.get("donation_id") or (decision.get("donation", {}) or {}).get("donation_id")

    if donation_id and not isinstance(decision.get("donation"), dict):
        latest = latest_processed_for_donation(donation_id)
        if isinstance(latest, dict) and isinstance(latest.get("donation"), dict):
            decision["donation"] = latest.get("donation")

    if donation_id and (not isinstance(decision.get("donation"), dict) or not decision.get("donation")):
        latest = latest_processed_for_donation(donation_id)
        if isinstance(latest, dict) and isinstance(latest.get("donation"), dict):
            decision["donation"] = latest.get("donation")

    if donation_id:
        base_record = None
        for item in build_donation_flow_items():
            if item.get("donation_id") == donation_id:
                base_record = item
                break
        decision["identity"] = load_donation_identity(donation_id, base_record or decision.get("donation", {}) or {})

    return decision


def prepare_decision_items():
    decision_items = load_json_files(DATA_ROOT / "decisions")
    completed_donations = set()

    for item in decision_items:
        data = item.get("data", {})
        if isinstance(data, dict) and data.get("status") == "planting_completed":
            donation_id = data.get("donation_id")
            if donation_id:
                completed_donations.add(donation_id)

    for item in decision_items:
        data = item.get("data", {})
        item["summary"] = selected_option_summary(data) if isinstance(data, dict) else {}

        donation_id = data.get("donation_id") if isinstance(data, dict) else None
        status = data.get("status") if isinstance(data, dict) else None

        item["duplicate_warning"] = (
            donation_id in completed_donations
            and status != "planting_completed"
        )

    return decision_items


def load_latest_processed_donation():
    items = load_processed_items()

    if not items:
        return None

    items.sort(key=lambda x: x.get("modified", 0), reverse=True)
    item = items[0]
    data = item.get("data", {})

    donation = data.get("donation", {}) if isinstance(data, dict) else {}

    return {
        "file": item.get("file"),
        "donation_id": donation.get("donation_id", "—"),
        "amount_pi": donation.get("amount_pi", "—"),
        "donor": donation.get("donor", "—"),
        "tx_hash": donation.get("tx_hash", "—"),
        "route": data.get("route", "—"),
        "route_label": route_label(data.get("route")),
        "status": data.get("workflow_status", "—"),
        "status_label": status_label(data.get("workflow_status")),
        "message": data.get("workflow_message", "—"),
        "required_co2": data.get("required_co2_kg", "—"),
        "next_step": next_step_for_process(data.get("workflow_status")),
        "processed_at": data.get("processed_at", "—")
    }


def latest_status_by_donation():
    latest = {}

    for item in load_processed_items():
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        donation = data.get("donation", {})
        donation_id = donation.get("donation_id")

        if not donation_id:
            continue

        modified = item.get("modified", 0)

        if donation_id not in latest or modified > latest[donation_id].get("modified", 0):
            latest[donation_id] = {
                "modified": modified,
                "workflow_status": data.get("workflow_status"),
                "file": item.get("file")
            }

    return latest


def load_blocked_donations():
    items = load_processed_items()
    completed_ids = completed_donation_ids_from_processed()
    latest_by_id = latest_status_by_donation()
    blocked = []

    for item in items:
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        status = data.get("workflow_status", "")
        donation = data.get("donation", {})
        donation_id = donation.get("donation_id")

        if not donation_id:
            continue

        if not str(status).startswith("blocked") and status != "error":
            continue

        if donation_id in completed_ids:
            continue

        latest_record = latest_by_id.get(donation_id, {})
        if item.get("modified", 0) < latest_record.get("modified", 0):
            continue

        blocked.append({
            "file": item.get("file"),
            "donation_id": donation_id,
            "amount_pi": donation.get("amount_pi", "—"),
            "route": data.get("route", "—"),
            "route_label": route_label(data.get("route")),
            "status": status,
            "status_label": status_label(status),
            "message": data.get("workflow_message", "—"),
            "required_co2": data.get("required_co2_kg", "—"),
            "next_step": next_step_for_process(status),
            "modified": item.get("modified", 0)
        })

    blocked.sort(key=lambda x: x.get("modified", 0), reverse=True)
    return blocked


def pool_stats_from_json():
    """Overview count for shared CO₂ reserves only."""
    pools_path = DATA_ROOT / "co2-pool" / "pools"
    pools = [item["data"] for item in load_json_files(pools_path)
             if isinstance(item.get("data"), dict)]
    shared = [pool for pool in pools
              if pool.get("pool_availability", pool.get("availability", "shared")) == "shared"
              and pool.get("allocation_basis", "co2") == "co2"]
    stats = {"active": 0, "low": 0, "empty": 0, "total": len(shared)}
    for pool in shared:
        status = pool.get("status")
        total = pool.get("total_co2_kg", 0) or 0
        remaining = pool.get("remaining_co2_kg", 0) or 0
        if status == "closed" or remaining <= 0:
            stats["empty"] += 1
        elif total > 0 and (remaining / total) < 0.2:
            stats["low"] += 1
        else:
            stats["active"] += 1
    return stats


def pending_direct_confirmations():
    pending = []

    for item in prepare_decision_items():
        data = item.get("data", {})
        if isinstance(data, dict) and data.get("status") in ["selected", "selected_pending_planting"] and not item.get("duplicate_warning"):
            pending.append(item)

    return pending


def pending_decision_file_for_donation(donation_id):
    """Return the newest pending planting decision filename for one donation."""
    matches = []
    for item in prepare_decision_items():
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue
        if data.get("donation_id") != donation_id:
            continue
        if data.get("status") not in ["selected", "selected_pending_planting", "planting_failed"]:
            continue
        matches.append(item)

    if not matches:
        return None

    matches.sort(key=lambda item: item.get("modified", 0), reverse=True)
    return matches[0].get("file")


def pending_decision_href_for_donation(donation_id):
    decision_file = pending_decision_file_for_donation(donation_id)
    if not decision_file:
        return None
    return f"/confirm_planting/{decision_file}"


def pending_planting_count():
    return len(pending_direct_confirmations())


def donation_id_from_suggestion_data(data, fallback_file=None):
    if not isinstance(data, dict):
        return None

    donation = data.get("donation", {}) if isinstance(data.get("donation", {}), dict) else {}

    return (
        data.get("donation_id")
        or donation.get("donation_id")
        or (fallback_file.replace("suggestion_", "").replace(".json", "") if fallback_file else None)
    )


def pending_project_selection_items():
    """
    Direct planting suggestions waiting for human project/species selection.
    These are already processed donations, not pending donations.
    """
    suggestions = attach_human_labels_to_suggestions(prepare_suggestion_items())

    decided_or_planted = set()

    for decision in prepare_decision_items():
        data = decision.get("data", {})
        if isinstance(data, dict) and data.get("donation_id"):
            decided_or_planted.add(data.get("donation_id"))

    for planting in load_json_files(DATA_ROOT / "plantings"):
        data = planting.get("data", {})
        if isinstance(data, dict) and data.get("donation_id"):
            decided_or_planted.add(data.get("donation_id"))

    pending = []

    for suggestion in suggestions:
        data = suggestion.get("data", {})
        donation_id = donation_id_from_suggestion_data(data, suggestion.get("file"))

        if not donation_id:
            continue

        if donation_id in decided_or_planted:
            continue

        suggestion["donation_id"] = donation_id
        pending.append(suggestion)

    return pending




def pool_action_status(queue=None):
    """
    Human/operator status for Admin Home.

    Green = pools are usable.
    Yellow = reserve is low but not blocking.
    Red = a pending small donation cannot be covered, or no usable pool exists.
    """
    pools_path = DATA_ROOT / "co2-pool" / "pools"
    pool_items = [item["data"] for item in load_json_files(pools_path)]

    active_pools = []
    total_remaining = 0
    highest_remaining = 0

    for pool in pool_items:
        if pool.get("status") != "active":
            continue
        if pool.get("allocation_basis", "co2") != "co2":
            continue
        if pool.get("pool_availability", "shared") != "shared":
            continue

        remaining = pool.get("remaining_co2_kg", 0) or 0
        if remaining <= 0:
            continue

        active_pools.append(pool)
        total_remaining += remaining
        highest_remaining = max(highest_remaining, remaining)

    pending_small = []
    for pending in queue or []:
        try:
            amount_pi = float(pending.get("amount_pi", 0))
            required_co2 = float(pending.get("required_co2", 0))
        except Exception:
            continue

        if amount_pi <= pending.get("pool_limit", 5):
            pending_small.append({
                "donation_id": pending.get("donation_id"),
                "required_co2": required_co2
            })

    blocked_small = []
    for item in pending_small:
        if highest_remaining < item["required_co2"]:
            blocked_small.append(item)

    if pending_small and blocked_small:
        return {
            "level": "critical",
            "label": "Action needed",
            "message": "A pending small donation cannot be covered by the current shared CO₂ pools.",
            "total_remaining": total_remaining,
            "active_count": len(active_pools),
            "blocked_small": blocked_small
        }

    if not active_pools:
        return {
            "level": "critical",
            "label": "No active pool",
            "message": "No active shared CO₂ pool is available for small donations.",
            "total_remaining": 0,
            "active_count": 0,
            "blocked_small": []
        }

    if len(active_pools) == 1 or total_remaining < 300:
        return {
            "level": "warning",
            "label": "Reserve getting low",
            "message": "Shared CO₂ pools are still usable, but reserves are getting low.",
            "total_remaining": total_remaining,
            "active_count": len(active_pools),
            "blocked_small": []
        }

    return {
        "level": "healthy",
        "label": "Ready",
        "message": "Shared CO₂ pools are ready for small donations.",
        "total_remaining": total_remaining,
        "active_count": len(active_pools),
        "blocked_small": []
    }


def action_summary(queue, direct_confirmations, blocked_items, catalog, pool_action, project_selection_items=None):
    actions = []
    project_selection_items = project_selection_items or []

    if blocked_items:
        actions.append({
            "level": "critical",
            "title": "Issues or warnings need review",
            "message": f"{len(blocked_items)} item(s) are blocking or need attention.",
            "href": "/blocked",
            "button": "Open details"
        })

    if catalog.get("status") in ["missing", "old"]:
        actions.append({
            "level": "critical",
            "title": "Tree catalog needs refresh",
            "message": catalog.get("message", "Tree catalog is missing or old."),
            "href": None,
            "form_action": "/run/refresh_catalog",
            "button": "Refresh tree catalog"
        })
    elif catalog.get("status") == "warning":
        actions.append({
            "level": "warning",
            "title": "Tree catalog is getting old",
            "message": catalog.get("message", "Refresh before serious planting."),
            "href": None,
            "form_action": "/run/refresh_catalog",
            "button": "Refresh tree catalog"
        })

    if pool_action.get("level") == "critical":
        actions.append({
            "level": "critical",
            "title": "Shared CO₂ pool action needed",
            "message": pool_action.get("message"),
            "href": "/pool/create?allocation_basis=co2&pool_availability=shared&target_value=" + str(int(max([item["required_co2"] for item in pool_action.get("blocked_small", [])] or [1000]))),
            "button": "Create shared CO₂ pool"
        })

    if queue:
        actions.append({
            "level": "warning",
            "title": "Donations waiting",
            "message": f"{len(queue)} donation(s) are waiting for the next step.",
            "href": "/planting#donations-waiting",
            "button": "Open donations waiting"
        })

    if project_selection_items:
        actions.append({
            "level": "warning",
            "title": "Project selection waiting",
            "message": f"{len(project_selection_items)} direct planting suggestion(s) are ready for project selection.",
            "href": "/records",
            "button": "Open donation"
        })

    if direct_confirmations:
        actions.append({
            "level": "warning",
            "title": "Planting confirmation waiting",
            "message": f"{len(direct_confirmations)} planting(s) are waiting for confirmation.",
            "href": "/decisions",
            "button": "Open planting confirmations"
        })

    return actions

def catalog_status():
    candidates = [FULL_CATALOG_FILE, CATALOG_FILE]
    existing = [path for path in candidates if path.exists()]

    if not existing:
        return {
            "exists": False,
            "status": "missing",
            "label": "Missing",
            "message": "No Tree-Nation catalog file found.",
            "age_hours": None,
            "file": "—",
            "updated_at": "—"
        }

    # Use newest available catalog file
    path = max(existing, key=lambda p: p.stat().st_mtime)
    modified_ts = path.stat().st_mtime
    modified_dt = datetime.fromtimestamp(modified_ts, UTC)
    age_hours = (datetime.now(UTC) - modified_dt).total_seconds() / 3600

    if age_hours <= 24:
        status = "fresh"
        label = "Fresh"
        message = "Catalog is fresh enough for normal use."
    elif age_hours <= 72:
        status = "warning"
        label = "Outdated"
        message = "Catalog is older than 24 hours. Refresh before serious planting."
    else:
        status = "old"
        label = "Old"
        message = "Catalog is old. Refresh before using planting suggestions."

    return {
        "exists": True,
        "status": status,
        "label": label,
        "message": message,
        "age_hours": round(age_hours, 1),
        "file": str(path),
        "updated_at": modified_dt.strftime("%Y-%m-%d %H:%M UTC")
    }


def run_catalog_refresh():
    candidate_scripts = [
        SCRIPTS_DIR / "fetch_full_catalog.py",
        SCRIPTS_DIR / "fetch_catalog.py",
        SCRIPTS_DIR / "fetch_projects.py",
        SCRIPTS_DIR / "refresh_catalog.py",
        SCRIPTS_DIR / "tree_nation_catalog.py"
    ]

    for script in candidate_scripts:
        if script.exists():
            result = subprocess.run(
                ["python", str(script)],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout
            if result.stderr:
                output += "\n\n--- STDERR ---\n" + result.stderr

            return {
                "ran": True,
                "script": str(script),
                "exit_code": result.returncode,
                "output": output
            }

    return {
        "ran": False,
        "script": None,
        "exit_code": None,
        "output": "No known catalog refresh script found in scripts/."
    }


def raw_overview_output():
    result = subprocess.run(
        ["python", str(SCRIPTS_DIR / "overview.py")],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True
    )

    output = result.stdout
    if result.stderr:
        output += "\n\n--- STDERR ---\n" + result.stderr

    return output





def load_json_path(path, default=None):
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json_path(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def pool_next_id():
    pools_dir = DATA_ROOT / "co2-pool" / "pools"
    pools_dir.mkdir(parents=True, exist_ok=True)

    highest = 0

    for file in pools_dir.glob("pool_*.json"):
        match = re.fullmatch(r"pool_(\d+)\.json", file.name)
        if match:
            highest = max(highest, int(match.group(1)))

    return f"pool_{highest + 1:03d}"


def pool_name_exists(pool_name):
    """Return True when a human-readable pool name already exists (trimmed/case-insensitive)."""
    normalized = (pool_name or "").strip().casefold()
    if not normalized:
        return False

    pools_dir = DATA_ROOT / "co2-pool" / "pools"
    if not pools_dir.exists():
        return False

    for file in pools_dir.glob("pool_*.json"):
        pool = load_json_path(file, default={}) or {}
        existing = str(pool.get("name") or "").strip().casefold()
        if existing and existing == normalized:
            return True
    return False


def pool_species_metadata(species_id):
    """Read optional cached Tree-Nation species metadata from Project Intelligence."""
    path = DATA_ROOT / "project-intelligence" / "species" / f"species_{species_id}.json"
    data = load_json_path(path, default={})
    tn = data.get("tree_nation", {}) if isinstance(data, dict) else {}

    def named(value):
        if isinstance(value, dict):
            return value.get("name") or ""
        return value or ""

    def english_common_name(value):
        """Return one English common name when Tree-Nation provides one."""
        if not value:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            # Some payloads use language keys; others use a single name object.
            for key in ("en", "EN", "english", "English"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            language = str(value.get("language") or value.get("lang") or "").lower()
            name = value.get("name") or value.get("value")
            if language in {"en", "eng", "english"} and isinstance(name, str) and name.strip():
                return name.strip()
            if isinstance(name, str) and name.strip():
                return name.strip()
            for candidate in value.values():
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return ""
        if isinstance(value, list):
            # Prefer explicitly English entries.
            for item in value:
                if isinstance(item, dict):
                    language = str(item.get("language") or item.get("lang") or "").lower()
                    name = item.get("name") or item.get("value")
                    if language in {"en", "eng", "english"} and isinstance(name, str) and name.strip():
                        return name.strip()
            for item in value:
                candidate = english_common_name(item)
                if candidate:
                    return candidate
        return ""

    common_names = tn.get("common_names")
    if isinstance(common_names, str):
        common_names_display = common_names.strip()
    elif isinstance(common_names, list):
        parts = []
        for item in common_names:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("value")
                if isinstance(name, str) and name.strip():
                    parts.append(name.strip())
        common_names_display = "; ".join(parts)
    elif isinstance(common_names, dict):
        parts = [str(v).strip() for v in common_names.values() if isinstance(v, str) and v.strip()]
        common_names_display = "; ".join(parts)
    else:
        common_names_display = ""

    return {
        "category": named(tn.get("category")),
        "origin_type": named(tn.get("origin_type")),
        "foliage_type": named(tn.get("foliage_type")),
        "family": tn.get("family") or "",
        "common_name_en": english_common_name(common_names),
        "common_names": common_names_display,
        "image_url": tn.get("image_url") or "",
        "height_m": tn.get("height_m") or "",
        "lifespan_years": tn.get("average_natural_life_span_years") or "",
        "particularities": tn.get("particularities") or "",
        "planter_likes": tn.get("planter_likes") or "",
        "details_endpoint": tn.get("details_endpoint") or "",
    }


def pool_catalog_options(target_value, allocation_basis="co2", show_all=False):
    """Build browser pool options without changing existing pool accounting.

    Green = one of the normal top-five recommendations that fully meets target.
    Orange = fully meets target but is outside the normal top-five recommendations.
    Red = available stock cannot fully meet the entered target; selectable only as an
    explicit operator exception.
    """
    catalog = load_json_path(DATA_ROOT / "tree-nation" / "full_catalog.json", default={})
    all_options = []
    blacklist = ["test", "marta"]
    basis = "trees" if str(allocation_basis).lower() == "trees" else "co2"
    target_value = max(1, int(target_value))
    config = load_json(CONFIG_FILE, {}) or {}
    try:
        pi_value_eur = float(config.get("pi_value", 0.1) or 0.1)
    except Exception:
        pi_value_eur = 0.1
    try:
        min_co2_per_pi = float(config.get("min_co2_per_pi", 30) or 30)
    except Exception:
        min_co2_per_pi = 30.0

    for project in catalog.get("projects", []):
        project_id = project.get("project_id")
        project_name = project.get("project_name")

        for species in project.get("species", []):
            species_id = species.get("id")
            species_name = species.get("name")
            price = species.get("price", 0) or 0
            co2 = species.get("life_time_CO2", 0) or 0
            stock = int(species.get("stock", 0) or 0)

            combined = f"{project_name} {species_name}".lower()
            if any(word in combined for word in blacklist):
                continue
            if not project_id or not species_id or price <= 0 or co2 <= 0 or stock <= 0:
                continue

            if basis == "trees":
                requested_quantity = target_value
                quantity = min(requested_quantity, stock)
                target_metric = requested_quantity
                achieved_metric = quantity
            else:
                requested_quantity = -(-target_value // int(co2))
                quantity = min(requested_quantity, stock)
                target_metric = target_value
                achieved_metric = quantity * co2

            if quantity <= 0:
                continue

            total_co2 = quantity * co2
            total_cost = round(quantity * price, 2)
            co2_per_eur = round(co2 / price, 2)
            eur_per_tree = round(float(price), 2)
            # pi_value is configured as EUR per Pi. Therefore kg CO2/Pi for this
            # species is CO2/EUR multiplied by the current EUR/Pi planning value.
            co2_per_pi = round(co2_per_eur * pi_value_eur, 2) if pi_value_eur > 0 else 0
            pi_required = round(total_cost / pi_value_eur, 2) if pi_value_eur > 0 else 0
            coverage = round((achieved_metric / target_metric) * 100, 1) if target_metric else 0
            meets_quantity_target = achieved_metric >= target_metric
            meets_co2_standard = co2_per_pi >= min_co2_per_pi
            # A normal/green pool option must satisfy both the requested pool target
            # and TPF's configured minimum environmental return per Pi.
            meets_target = meets_quantity_target and meets_co2_standard

            metadata = pool_species_metadata(species_id)
            all_options.append({
                "project_id": project_id,
                "project_name": project_name,
                "species_id": species_id,
                "species_name": species_name,
                "price": price,
                "co2_per_tree": co2,
                "stock": stock,
                "quantity_needed": quantity,
                "requested_quantity": requested_quantity,
                "total_co2": total_co2,
                "total_cost": total_cost,
                "currency": "EUR",
                "eur_per_tree": eur_per_tree,
                "co2_per_eur": co2_per_eur,
                "co2_per_pi": co2_per_pi,
                "pi_required": pi_required,
                "pi_value_eur": pi_value_eur,
                "min_co2_per_pi": min_co2_per_pi,
                "meets_quantity_target": meets_quantity_target,
                "meets_co2_standard": meets_co2_standard,
                "allocation_basis": basis,
                "target_value": target_value,
                "coverage_percent": coverage,
                "meets_target": meets_target,
                "category": metadata.get("category", ""),
                "origin_type": metadata.get("origin_type", ""),
                "foliage_type": metadata.get("foliage_type", ""),
                "family": metadata.get("family", ""),
                "common_name_en": metadata.get("common_name_en", ""),
                "common_names": metadata.get("common_names", ""),
                "image_url": metadata.get("image_url", ""),
                "height_m": metadata.get("height_m", ""),
                "lifespan_years": metadata.get("lifespan_years", ""),
                "particularities": metadata.get("particularities", ""),
                "planter_likes": metadata.get("planter_likes", ""),
                "details_endpoint": metadata.get("details_endpoint", ""),
            })

    valid = [o for o in all_options if o["meets_target"]]
    invalid = [o for o in all_options if not o["meets_target"]]
    valid.sort(key=lambda item: (item["total_cost"], -item["co2_per_eur"]))
    invalid.sort(key=lambda item: (-item["coverage_percent"], item["total_cost"], -item["co2_per_eur"]))

    recommended_keys = {(o["project_id"], o["species_id"]) for o in valid[:5]}
    for option in valid:
        if (option["project_id"], option["species_id"]) in recommended_keys:
            option["option_status"] = "green"
            option["status_label"] = "Top 5"
            option["status_reason"] = "Meets the target and is in the normal top-five lowest-cost / high-efficiency shortlist."
        else:
            option["option_status"] = "orange"
            option["status_label"] = "Valid alternative"
            option["status_reason"] = "Meets the target and remains fully selectable, but ranks outside the current Top 5."

    for option in invalid:
        option["option_status"] = "red"
        option["status_label"] = "Exception"
        reasons = []
        if not option.get("meets_quantity_target"):
            if basis == "trees":
                reasons.append(f"Available stock provides {option['quantity_needed']} of {target_value} target trees.")
            else:
                reasons.append(f"Available stock provides {option['total_co2']} of {target_value} target kg CO2.")
        if not option.get("meets_co2_standard"):
            reasons.append(
                f"CO2/Pi is {option['co2_per_pi']} kg, below the configured minimum of {option['min_co2_per_pi']:g} kg/Pi."
            )
        option["status_reason"] = " ".join(reasons) or "Outside current TPF pool rules."

    if show_all:
        return valid + invalid
    return valid[:5]


def default_pool_message(pool_id, pool_name, allocation_basis, target_value, selected, pool_availability="shared"):
    """Default public Tree-Nation message; editable before the live API call."""
    project_name = selected.get("project_name", "selected project")
    species_name = selected.get("species_name", "selected species")
    display_name = pool_name or pool_id

    availability = "dedicated" if str(pool_availability).lower() == "dedicated" else "shared"
    if allocation_basis == "trees":
        if availability == "dedicated":
            impact_line = f"{selected.get('quantity_needed', target_value)} trees planted for this dedicated planting pool."
            pool_type = "Dedicated Tree Pool"
        else:
            impact_line = f"{selected.get('quantity_needed', target_value)} trees planted for this shared tree pool."
            pool_type = "Shared Tree Pool"
    else:
        if availability == "dedicated":
            impact_line = f"{selected.get('total_co2', target_value)} kg CO2 planted for this dedicated planting pool."
            pool_type = "Dedicated CO2 Pool"
        else:
            impact_line = f"{selected.get('total_co2', target_value)} kg CO2 reserve created for future Pioneer donations."
            pool_type = "Shared CO2 Pool"

    return (
        f"TPF {pool_type}: {display_name} 🌱\n"
        f"{impact_line}\n"
        f"Project: {project_name} / {species_name}.\n"
        "Small contributions, real trees, collective impact.\n"
        "#ThePioneerForest"
    )


def create_pool_from_browser(pool_id, pool_name, allocation_basis, pool_availability, target_value, selected, tree_nation_message=None, exception_reason=None, owner_kind=None, owner_partner_id=None):
    load_dotenv(ENV_FILE)

    api_token = os.getenv("TREE_NATION_API_TOKEN")
    base_url = os.getenv("BASE_URL")

    if not api_token or not base_url:
        return {"ok": False, "message": "Missing TREE_NATION_API_TOKEN or BASE_URL in .env", "pool_file": None, "raw_response_file": None}

    basis = "trees" if str(allocation_basis).lower() == "trees" else "co2"
    availability = "dedicated" if str(pool_availability).lower() == "dedicated" else "shared"
    # Check again immediately before the irreversible Tree-Nation request.
    owner_kind, owner_partner_id = _validated_pool_owner(availability, owner_kind, owner_partner_id)
    pools_dir = DATA_ROOT / "co2-pool" / "pools"
    tree_nation_dir = DATA_ROOT / "tree-nation"
    pools_dir.mkdir(parents=True, exist_ok=True)
    tree_nation_dir.mkdir(parents=True, exist_ok=True)
    pool_file = pools_dir / f"{pool_id}.json"

    if pool_file.exists():
        return {"ok": False, "message": f"Pool already exists: {pool_id}", "pool_file": str(pool_file), "raw_response_file": None}

    url = f"{base_url}/plant"
    message = (tree_nation_message or "").strip() or default_pool_message(pool_id, pool_name, basis, target_value, selected, availability)
    payload = {"project_id": selected["project_id"], "species_id": selected["species_id"], "quantity": selected["quantity_needed"], "message": message}
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)

    raw_result = {
        "created_at": now_iso(),
        "request": {"url": url, "payload": payload},
        "selected_option": selected,
        "pool_name": pool_name,
        "allocation_basis": basis,
        "pool_availability": availability,
        "owner_kind": owner_kind,
        "owner_partner_id": owner_partner_id,
        "target_value": int(target_value),
        "operator_exception_reason": exception_reason,
        "response": {"status_code": response.status_code, "text": response.text}
    }
    try:
        response_json = response.json()
    except Exception:
        response_json = None
    raw_result["response"]["json"] = response_json
    raw_file = tree_nation_dir / f"{pool_id}_selected_api_response.json"
    save_json_path(raw_file, raw_result)

    if response.status_code < 200 or response.status_code >= 300:
        return {"ok": False, "message": f"Tree-Nation API returned status {response.status_code}", "pool_file": None, "raw_response_file": str(raw_file)}
    if not response_json or response_json.get("status") != "ok":
        return {"ok": False, "message": "Tree-Nation API response was not OK", "pool_file": None, "raw_response_file": str(raw_file)}

    trees = response_json.get("trees", [])
    certificates = []
    for tree in trees:
        certificates.append({
            "tree_id": tree.get("id"), "token": tree.get("token"), "certificate_url": tree.get("certificate_url"),
            "collect_url": tree.get("collect_url"), "public_proof_url": tree.get("certificate_url"), "public_use_collect_url": False,
            "country": tree.get("country"), "project_id": tree.get("project_id"), "project_name": tree.get("project_name"),
            "project_url": tree.get("project_url"), "species_id": tree.get("species_id"), "species_name": tree.get("species_name"),
            "co2_kg": tree.get("species_life_time_CO2", 0), "quantity_requested": selected["quantity_needed"], "grouped_certificate": True
        })

    quantity = int(selected["quantity_needed"])
    total_co2 = selected["total_co2"]
    display_name = (pool_name or "").strip() or f"TPF {'Dedicated' if availability == 'dedicated' else 'Shared'} {'Tree' if basis == 'trees' else 'CO2'} Pool {pool_id}"
    pool = {
        "pool_id": pool_id,
        "name": display_name,
        "allocation_basis": basis,
        "pool_availability": availability,
        "owner_kind": owner_kind,
        "owner_partner_id": owner_partner_id,
        "ownership_history": [{"at": now_iso(), "action": "owner_set_at_planting",
                               "owner_kind": owner_kind, "partner_id": owner_partner_id}],
        "status": "active",
        "source": f"Tree-Nation API browser-created {availability} pool",
        "tree_nation_message": message,
        "tree_nation_hashtag_required": "#ThePioneerForest",
        "payment_id": response_json.get("payment_id"),
        "quantity": quantity,
        "api_tree_objects_returned": len(trees),
        "total_co2_kg": total_co2,
        "allocated_co2_kg": 0,
        "remaining_co2_kg": total_co2,
        "warning_percent": 20,
        "critical_percent": 10,
        "selected_project_id": selected["project_id"],
        "selected_project_name": selected["project_name"],
        "selected_species_id": selected["species_id"],
        "selected_species_name": selected["species_name"],
        "expected_total_cost": selected["total_cost"],
        "option_status_at_creation": selected.get("option_status"),
        "option_status_reason": selected.get("status_reason"),
        "operator_exception_reason": exception_reason,
        "certificates": certificates,
        "created_at": now_iso(),
        "closed_at": None,
        "note": f"Browser-created {availability} pool. Tree-Nation may return one grouped certificate object for multiple trees. Accounting uses selected requested quantity, not the number of API tree objects."
    }
    if basis == "trees":
        pool.update({
            "target_trees": int(target_value),
            "total_trees": quantity,
            "allocated_trees": 0,
            "remaining_trees": quantity,
            "co2_metadata_only": True
        })
    else:
        pool["target_co2_kg"] = int(target_value)

    save_json_path(pool_file, pool)
    return {"ok": True, "message": f"{'Dedicated' if availability == 'dedicated' else 'Shared'} pool created successfully.", "pool_file": str(pool_file), "raw_response_file": str(raw_file), "pool": pool}


def dashboard_pool_view():
    pools_path = DATA_ROOT / "co2-pool" / "pools"
    items = load_json_files(pools_path)

    active = []
    inactive = []

    for item in items:
        pool = item.get("data", {})
        basis = pool.get("allocation_basis", "co2")
        availability = pool.get("pool_availability", pool.get("availability", "shared"))
        if basis == "trees":
            total = pool.get("total_trees", pool.get("quantity", 0)) or 0
            remaining = total if availability == "dedicated" else (pool.get("remaining_trees", 0) or 0)
            unit = "trees"
        else:
            total = pool.get("total_co2_kg", 0) or 0
            remaining = total if availability == "dedicated" else (pool.get("remaining_co2_kg", 0) or 0)
            unit = "kg CO2"
        status = pool.get("status", "unknown")

        entry = {
            "pool_id": pool.get("pool_id", "unknown"),
            "name": pool.get("name") or pool.get("pool_id", "unknown"),
            "allocation_basis": basis,
            "availability": pool.get("pool_availability", pool.get("availability", "shared")),
            "remaining": remaining,
            "unit": unit,
            "status": status
        }

        if status == "active" and (availability == "dedicated" or remaining > 0):
            if availability == "dedicated":
                entry["level"] = "healthy"
                entry["label"] = ""
            elif total > 0 and (remaining / total) < 0.2:
                entry["level"] = "warning"
                entry["label"] = "Low reserve"
            else:
                entry["level"] = "healthy"
                entry["label"] = "Healthy"
            active.append(entry)
        else:
            entry["level"] = "inactive"
            entry["label"] = "Inactive"
            inactive.append(entry)

    active.sort(key=lambda x: x["remaining"], reverse=True)
    inactive.sort(key=lambda x: x["pool_id"])
    return {"active": active, "inactive": inactive}


def human_decision_title(item):
    data = item.get("data", {})
    summary = item.get("summary", {})

    donation_id = data.get("donation_id", "unknown donation")
    project = summary.get("project", "unknown project")
    species = summary.get("species", "unknown species")

    return f"{donation_id} — {project} / {species}"


def human_suggestion_title(item):
    data = item.get("data", {})
    donation = data.get("donation", {}) if isinstance(data, dict) else {}
    donation_id = data.get("donation_id") or donation.get("donation_id") or "unknown donation"
    amount_pi = data.get("amount_pi") or donation.get("amount_pi") or "?"
    return f"{donation_id} — {amount_pi} Pi"


def attach_human_labels_to_decisions(items):
    for item in items:
        item["human_title"] = human_decision_title(item)
    return items


def attach_human_labels_to_suggestions(items):
    for item in items:
        item["human_title"] = human_suggestion_title(item)
    return items


def latest_processed_for_donation(donation_id):
    if not donation_id:
        return None

    matches = []

    for item in load_processed_items():
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        donation = data.get("donation", {})
        if donation.get("donation_id") == donation_id:
            matches.append(item)

    if not matches:
        return None

    matches.sort(key=lambda x: x.get("modified", 0), reverse=True)
    return matches[0].get("data", {})


def redirect_after_processing(donation_id):
    latest = latest_processed_for_donation(donation_id)

    if not latest:
        return redirect("/records")

    route = latest.get("route")
    status = latest.get("workflow_status")

    # Direct planting donations:
    # continue immediately to project selection
    if route == "direct_planting_suggestions":
        return redirect(f"/record/{donation_id}")

    # Problems / blocked workflow:
    # send operator directly to issues page
    if status and str(status).startswith("blocked"):
        return redirect("/blocked")

    if status == "error":
        return redirect("/blocked")

    # Shared CO₂ pool donations:
    # already completed automatically
    # show Donation Flow so the operator clearly sees the result
    return redirect("/records")



def donation_flow_status_badge(status):
    labels = {
        "waiting": ("status-warning", "Waiting"),
        "covered_by_pool": ("status-active", "Covered by shared pool"),
        "project_options_ready": ("status-warning", "Project options ready"),
        "approval_waiting": ("status-warning", "Waiting for planting confirmation"),
        "planted": ("status-active", "Planted"),
        "issue": ("status-closed", "Needs attention"),
        "unknown": ("muted", "Unknown")
    }
    css_class, label = labels.get(status, ("muted", status))
    return {"class": css_class, "label": label}


def load_operational_settings():
    config = load_json(CONFIG_FILE, {}) or {}

    return {
        "pi_value": display_number(config.get("pi_value", 0.15)),
        "currency": config.get("currency", "EUR"),
        "min_co2_per_pi": display_number(config.get("min_co2_per_pi", 30)),
        "co2_pool_auto_limit_pi": display_number(config.get("co2_pool_auto_limit_pi", 5)),
        "tpf_addition_percent": display_number(config.get("tpf_addition_percent") if config.get("tpf_addition_percent") not in (None, "") else 25),
        "config_file": str(CONFIG_FILE)
    }


def parse_number_input(value, fallback):
    """
    Accept both English decimal dots and German decimal commas.
    Examples:
    - 0.13
    - 0,13
    - 30
    """
    if value is None or str(value).strip() == "":
        value = fallback

    value_text = str(value).strip().replace(",", ".")

    return float(value_text)


def display_number(value):
    """
    Human-friendly display for settings:
    30.0 -> 30
    0.13 -> 0.13
    """
    try:
        value_float = float(value)
    except Exception:
        return value

    if value_float.is_integer():
        return int(value_float)

    return value_float


def save_operational_settings(form):
    current = load_json(CONFIG_FILE, {}) or {}

    confirmation = (form.get("confirmation") or "").strip()

    if confirmation != "YES":
        return {
            "ok": False,
            "message": "Settings were not changed. Type YES and click Save settings to confirm operational value changes."
        }

    try:
        pi_value = parse_number_input(form.get("pi_value"), current.get("pi_value", 0.15))
        min_co2_per_pi = parse_number_input(form.get("min_co2_per_pi"), current.get("min_co2_per_pi", 30))
        co2_pool_auto_limit_pi = parse_number_input(form.get("co2_pool_auto_limit_pi"), current.get("co2_pool_auto_limit_pi", 5))
    except Exception:
        return {
            "ok": False,
            "message": "Settings were not changed. Please use numbers like 0.13 or 0,13."
        }

    currency = (form.get("currency") or current.get("currency") or "EUR").strip().upper()

    addition_input = (form.get("tpf_addition_percent") or "").strip()
    if addition_input:
        try:
            addition_value = number(addition_input, "TPF addition")
        except ValueError as exc:
            return {"ok": False, "message": f"Settings were not changed. {exc}."}
        current["tpf_addition_percent"] = str(addition_value)

    current["pi_value"] = pi_value
    current["currency"] = currency
    current["min_co2_per_pi"] = min_co2_per_pi
    current["co2_pool_auto_limit_pi"] = co2_pool_auto_limit_pi
    current["updated_at"] = now_iso()
    current["update_note"] = "Changed through TPF Operations Center settings page."

    save_json(CONFIG_FILE, current)

    return {
        "ok": True,
        "message": "Settings updated. Remember: public TPF communication may be needed before using changed operational rules."
    }



# ---------------------------------------------------------------------------
# Donation identity / operator display
# ---------------------------------------------------------------------------

def donation_identity_dir():
    path = DATA_ROOT / "identity" / "donations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def donation_identity_file(donation_id):
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", donation_id or "unknown")
    return donation_identity_dir() / f"{safe_id}.json"


def wallet_identity_file():
    path = DATA_ROOT / "identity"
    path.mkdir(parents=True, exist_ok=True)
    return path / "wallet_display_names.json"


def wallet_address_from_record(record):
    if not isinstance(record, dict):
        return ""

    candidates = [
        record.get("from_address"),
        record.get("wallet_from"),
        record.get("sender_address"),
    ]

    donation = record.get("donation", {}) if isinstance(record.get("donation", {}), dict) else {}
    candidates.extend([
        donation.get("from_address"),
        donation.get("wallet_from"),
        donation.get("sender_address"),
    ])

    raw_wallet_tx = donation.get("raw_wallet_tx", {}) if isinstance(donation.get("raw_wallet_tx", {}), dict) else {}
    candidates.append(raw_wallet_tx.get("from"))
    candidates.append(raw_wallet_tx.get("from_address"))

    for value in candidates:
        value = str(value or "").strip()
        if value:
            return value
    return ""


def load_wallet_display_mappings():
    data = load_json(wallet_identity_file(), {}) or {}
    return data if isinstance(data, dict) else {}


def save_wallet_display_mapping(wallet_address, display_name, note=""):
    wallet_address = str(wallet_address or "").strip()
    display_name = str(display_name or "").strip()
    if not wallet_address or not display_name:
        return

    data = load_wallet_display_mappings()
    data[wallet_address] = {
        "display_name": display_name,
        "note": note,
        "confirmed_by": "TPF Operations Center",
        "updated_at": now_iso(),
    }
    save_json(wallet_identity_file(), data)


def mapped_display_name_for_record(record):
    wallet_address = wallet_address_from_record(record)
    if not wallet_address:
        return ""
    mapping = load_wallet_display_mappings().get(wallet_address, {})
    if isinstance(mapping, dict):
        return str(mapping.get("display_name") or "").strip()
    return ""


def wallet_note_from_record(record):
    if not isinstance(record, dict):
        return ""

    candidates = [record.get("memo_raw"), record.get("wallet_note")]
    donation = record.get("donation", {}) if isinstance(record.get("donation", {}), dict) else {}
    candidates.extend([donation.get("memo_raw"), donation.get("wallet_note")])

    raw_wallet_tx = donation.get("raw_wallet_tx", {}) if isinstance(donation.get("raw_wallet_tx", {}), dict) else {}
    candidates.extend([raw_wallet_tx.get("memo"), raw_wallet_tx.get("memo_raw")])

    for value in candidates:
        value = str(value or "").strip()
        if value:
            return value
    return ""


def default_display_name_for_record(record):
    mapped = mapped_display_name_for_record(record)
    if mapped:
        return mapped

    donor = str(record.get("donor") or "").strip()
    # Wallet-created donations should default to Arboris unless the operator confirms a name.
    if not donor or donor.startswith("Wallet donor"):
        return "Arboris"
    return donor


def load_donation_identity(donation_id, base_record=None):
    data = load_json(donation_identity_file(donation_id), None)
    if not isinstance(data, dict):
        data = {}

    display_name = data.get("display_name") or default_display_name_for_record(base_record or {})

    return {
        "schema": "tpf_donation_identity_v1",
        "donation_id": donation_id,
        "display_name": display_name,
        "private_note": data.get("private_note", data.get("internal_donor", "")),
        "wallet_note": data.get("wallet_note", wallet_note_from_record(base_record or {})),
        "message_note": data.get("message_note", data.get("public_note", "")),
        "include_wallet_note_in_message": bool(data.get("include_wallet_note_in_message", False)),
        "include_message_note_in_message": bool(data.get("include_message_note_in_message", data.get("include_public_note_in_message", False))),
        "tree_nation_manual_update": data.get("tree_nation_manual_update", {"needed": False, "updated": False}),
        "updated_at": data.get("updated_at"),
    }


def save_donation_identity(donation_id, identity):
    identity = dict(identity or {})
    identity["schema"] = "tpf_donation_identity_v1"
    identity["donation_id"] = donation_id
    identity["updated_at"] = now_iso()
    save_json(donation_identity_file(donation_id), identity)


def refresh_pending_decisions_for_identity(donation_id):
    """Keep existing approval files in sync after donor/message settings change.

    Safe behavior: only pending decisions are touched. Completed plantings are not changed.
    The final approval page will rebuild the editable Tree-Nation draft from the latest
    identity instead of keeping an old Arboris/name/message snapshot.
    """
    if not donation_id:
        return

    decisions_dir = DATA_ROOT / "decisions"
    if not decisions_dir.exists():
        return

    for path in decisions_dir.glob("*.json"):
        data = load_json(path, None)
        if not isinstance(data, dict):
            continue
        if data.get("donation_id") != donation_id:
            continue
        if data.get("status") not in ["selected_pending_planting", "planting_failed"]:
            continue

        enriched = enrich_decision_with_donation_identity(data)
        # Clear old draft so it is regenerated from the latest settings on next open.
        enriched["tree_nation_message"] = ""
        save_json(path, enriched)


def suggestion_item_for_donation(donation_id):
    for item in pending_project_selection_items():
        if item.get("donation_id") == donation_id:
            return item
    return None

def build_donation_flow_items():
    items_by_id = {}

    def ensure_item(donation_id):
        donation_id = donation_id or "unknown"
        if donation_id not in items_by_id:
            items_by_id[donation_id] = {
                "donation_id": donation_id,
                "date": "—",
                "timestamp": 0,
                "amount_pi": "—",
                "donor": "—",
                "tx_hash": "—",
                "route": "—",
                "status": "unknown",
                "status_badge": donation_flow_status_badge("unknown"),
                "next_action": "Review",
                "action_href": "/planting",
                "technical_file": "—",
                "source": "—",
                "from_address": "",
                "wallet_address": "",
                "wallet_mapping_known": False
            }
        return items_by_id[donation_id]

    for pending in pending_donation_queue():
        item = ensure_item(pending.get("donation_id"))
        modified = pending.get("modified", 0) or 0
        item.update({
            "date": datetime.fromtimestamp(modified, UTC).strftime("%Y-%m-%d %H:%M UTC") if modified else "—",
            "timestamp": modified,
            "amount_pi": pending.get("amount_pi", "—"),
            "donor": pending.get("donor", "—"),
            "tx_hash": pending.get("tx_hash", "—"),
            "from_address": pending.get("from_address", item.get("from_address", "")),
            "route": pending.get("expected_route", "—"),
            "status": "waiting",
            "status_badge": donation_flow_status_badge("waiting"),
            "next_action": "Start next step",
            "action_href": "/planting#donations-waiting",
            "technical_file": pending.get("file", "—"),
            "source": "pending"
        })

    # Apply older attempts first so the newest result owns the displayed status.
    for processed in sorted(load_processed_items(), key=lambda row: (row.get("modified", 0), row.get("file", ""))):
        data = processed.get("data", {})
        if not isinstance(data, dict):
            continue
        donation = data.get("donation", {})
        donation_id = donation.get("donation_id")
        item = ensure_item(donation_id)

        modified = processed.get("modified", 0) or 0
        if modified >= item.get("timestamp", 0):
            item["timestamp"] = modified
            item["date"] = datetime.fromtimestamp(modified, UTC).strftime("%Y-%m-%d %H:%M UTC") if modified else "—"

        item["amount_pi"] = donation.get("amount_pi", item.get("amount_pi", "—"))
        item["donor"] = donation.get("donor", item.get("donor", "—"))
        item["tx_hash"] = donation.get("tx_hash", item.get("tx_hash", "—"))
        item["from_address"] = (
            donation.get("from_address")
            or donation.get("sender_address")
            or donation.get("wallet_from")
            or item.get("from_address", "")
        )
        item["memo_raw"] = donation.get("memo_raw", item.get("memo_raw", ""))
        item["technical_file"] = processed.get("file", item.get("technical_file", "—"))

        route = data.get("route")
        workflow_status = data.get("workflow_status")

        if route == "co2_pool" and workflow_status == "completed":
            item.update({
                "route": "Shared CO2 Pool",
                "status": "covered_by_pool",
                "status_badge": donation_flow_status_badge("covered_by_pool"),
                "next_action": "Completed",
                "action_href": "/records",
                "source": "processed"
            })
        elif route == "direct_planting_suggestions" and workflow_status == "completed":
            item.update({
                "route": "Direct Planting",
                "status": "project_options_ready",
                "status_badge": donation_flow_status_badge("project_options_ready"),
                "next_action": "Choose project",
                "action_href": f"/record/{donation_id}",
                "source": "processed"
            })
        elif (workflow_status and str(workflow_status).startswith("blocked")) or workflow_status == "error":
            item.update({
                "status": "issue",
                "status_badge": donation_flow_status_badge("issue"),
                "next_action": "Open issues",
                "action_href": "/blocked",
                "source": "processed"
            })

    for suggestion in prepare_suggestion_items():
        data = suggestion.get("data", {})
        if not isinstance(data, dict):
            continue
        donation = data.get("donation", {})
        donation_id = data.get("donation_id") or donation.get("donation_id")
        if not donation_id:
            continue
        item = ensure_item(donation_id)
        if item.get("status") not in ["approval_waiting", "planted"]:
            item.update({
                "route": "Direct Planting",
                "status": "project_options_ready",
                "status_badge": donation_flow_status_badge("project_options_ready"),
                "next_action": "Choose project",
                "action_href": f"/record/{donation_id}",
                "technical_file": suggestion.get("file", item.get("technical_file", "—")),
                "source": "suggestion"
            })

    for decision in prepare_decision_items():
        data = decision.get("data", {})
        if not isinstance(data, dict):
            continue
        donation_id = data.get("donation_id")
        if not donation_id:
            continue
        item = ensure_item(donation_id)
        status = data.get("status")

        if status in ["selected", "selected_pending_planting"]:
            item.update({
                "route": "Direct Planting",
                "status": "approval_waiting",
                "status_badge": donation_flow_status_badge("approval_waiting"),
                "next_action": "Planting confirmation",
                "action_href": pending_decision_href_for_donation(donation_id) or "/decisions",
                "technical_file": decision.get("file", item.get("technical_file", "—")),
                "source": "decision"
            })
        elif status == "planting_completed":
            item.update({
                "route": "Direct Planting",
                "status": "planted",
                "status_badge": donation_flow_status_badge("planted"),
                "next_action": "Completed",
                "action_href": "/records",
                "technical_file": decision.get("file", item.get("technical_file", "—")),
                "source": "decision"
            })

    for planting in load_json_files(DATA_ROOT / "plantings"):
        data = planting.get("data", {})
        if isinstance(data, dict) and data.get("donation_id"):
            item = ensure_item(data.get("donation_id"))
            item.update({
                "route": "Direct Planting",
                "status": "planted",
                "status_badge": donation_flow_status_badge("planted"),
                "next_action": "Completed",
                "action_href": "/records",
                "technical_file": planting.get("file", item.get("technical_file", "—")),
                "source": "planting"
            })

    items = list(items_by_id.values())

    for item in items:
        item["detail_href"] = f"/record/{item.get('donation_id')}"
        identity = load_donation_identity(item.get("donation_id"), item)
        item["identity"] = identity
        item["display_name"] = identity.get("display_name") or default_display_name_for_record(item)
        item["wallet_address"] = wallet_address_from_record(item)
        item["wallet_mapping_known"] = bool(mapped_display_name_for_record(item))
        # In normal UI views, show the operator-approved public display name.
        # The raw donor string remains in related files / technical data.
        item["donor_raw"] = item.get("donor")
        item["donor"] = item["display_name"]

    items.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return items


def wallet_status_summary():
    """
    Safe Overview summary for Wallet Watcher.
    Must never break the Overview page if wallet files are missing or malformed.
    """
    try:
        sources = load_json(wallet_sources_file(), []) or []
        recent = load_json(wallet_transactions_file(), {}) or {}
        master = load_json(wallet_master_file(), {}) or {}

        if not isinstance(sources, list):
            sources = []
        if not isinstance(recent, dict):
            recent = {}
        if not isinstance(master, dict):
            master = {}

        records = master.get("transactions", [])
        if not isinstance(records, list):
            records = []

        matched = sum(1 for item in records if isinstance(item, dict) and item.get("history_match_status") == "matched_history")
        unmatched = sum(1 for item in records if isinstance(item, dict) and item.get("history_match_status") == "unmatched_blockchain")
        ignored = sum(1 for item in records if isinstance(item, dict) and item.get("history_match_status") == "ignored_test_payment")

        recent_transactions = recent.get("transactions", [])
        if not isinstance(recent_transactions, list):
            recent_transactions = []

        return {
            "source_count": len([source for source in sources if isinstance(source, dict) and source.get("enabled", True)]),
            "recent_count": len(recent_transactions),
            "master_total": len(records),
            "master_matched": matched,
            "master_unmatched": unmatched,
            "master_ignored": ignored,
            "last_fetch": recent.get("fetched_at", "Not checked yet")
        }

    except Exception as exc:
        return {
            "source_count": 0,
            "recent_count": 0,
            "master_total": 0,
            "master_matched": 0,
            "master_unmatched": 0,
            "master_ignored": 0,
            "last_fetch": f"Unavailable ({exc})"
        }


@app.route("/")
def admin_home():
    queue = pending_donation_queue()
    direct_confirmations = attach_human_labels_to_decisions(pending_direct_confirmations())
    project_selection_items = pending_project_selection_items()
    blocked_items = load_blocked_donations()
    pool_stats = pool_stats_from_json()
    catalog = catalog_status()
    pool_action = pool_action_status(queue)
    actions = action_summary(queue, direct_confirmations, blocked_items, catalog, pool_action, project_selection_items)
    wallet_status = wallet_status_summary()
    knowledge_status = knowledge_summary()
    post_status = posts_summary()
    actions = add_posts_to_overview_actions(actions, post_status)

    return render_template(
        "admin_home.html",
        queue=queue,
        direct_confirmations=direct_confirmations,
        project_selection_items=project_selection_items,
        blocked=blocked_items,
        pool_stats=pool_stats,
        pool_action=pool_action,
        actions=actions,
        action_stats={
            "pending": len(direct_confirmations),
            "blocked": len(blocked_items),
            "queue": len(queue),
            "project_selection": len(project_selection_items)
        },
        catalog=catalog,
        wallet_status=wallet_status,
        knowledge_status=knowledge_status,
        post_status=post_status
    )


@app.route("/planting")
def index():
    queue = pending_donation_queue()
    direct_confirmations = attach_human_labels_to_decisions(pending_direct_confirmations())
    project_selection_items = pending_project_selection_items()
    blocked_items = load_blocked_donations()
    pool_stats = pool_stats_from_json()
    catalog = catalog_status()
    pool_action = pool_action_status(queue)
    pool_view = dashboard_pool_view()
    actions = action_summary(queue, direct_confirmations, blocked_items, catalog, pool_action, project_selection_items)

    return render_template(
        "index.html",
        queue=queue,
        direct_confirmations=direct_confirmations,
        project_selection_items=project_selection_items,
        blocked=blocked_items,
        pool_stats=pool_stats,
        pool_action=pool_action,
        pool_view=pool_view,
        actions=actions,
        action_stats={
            "pending": len(direct_confirmations),
            "blocked": len(blocked_items),
            "queue": len(queue),
            "project_selection": len(project_selection_items)
        },
        catalog=catalog
    )


@app.route("/overview")
def overview():
    latest = load_latest_processed_donation()
    blocked = load_blocked_donations()
    queue = pending_donation_queue()
    pool_stats = pool_stats_from_json()
    action_stats = {
        "pending": pending_planting_count(),
        "blocked": len(blocked),
        "queue": len(queue)
    }

    return render_template(
        "overview.html",
        latest=latest,
        blocked=blocked,
        pool_stats=pool_stats,
        action_stats=action_stats,
        raw_output=raw_overview_output(),
        catalog=catalog_status()
    )


def species_metadata_index():
    """Read-only lookup of locally cached Tree-Nation species metadata.
    No API calls are made here.
    """
    index = {}
    species_dir = DATA_ROOT / "project-intelligence" / "species"
    if not species_dir.exists():
        return index

    for path in species_dir.glob("species_*.json"):
        data = load_json(path, {}) or {}
        if not isinstance(data, dict):
            continue
        species_id = data.get("species_id")
        if species_id is None:
            continue
        tn = data.get("tree_nation", {}) if isinstance(data.get("tree_nation"), dict) else {}

        def meta_name(value):
            return value.get("name", "") if isinstance(value, dict) else (value or "")

        index[str(species_id)] = {
            "common_names": tn.get("common_names") or "",
            "category": meta_name(tn.get("category")),
            "foliage_type": meta_name(tn.get("foliage_type")),
            "origin_type": meta_name(tn.get("origin_type")),
            "family": tn.get("family") or "",
            "image_url": tn.get("image_url") or "",
            "height_m": tn.get("height_m") or "",
            "lifespan_years": tn.get("average_natural_life_span_years") or "",
            "particularities": tn.get("particularities") or "",
            "planter_likes": tn.get("planter_likes") or "",
            "details_endpoint": tn.get("details_endpoint") or "",
        }
    return index


def species_search_aliases(species_name):
    """Small search-only aliases; never displayed as Tree-Nation metadata."""
    name = str(species_name or "").strip().lower()
    aliases = []
    # Bridge the everyday word used most often for the botanical genus Pinus.
    if name.startswith("pinus ") or name == "pinus":
        aliases.append("pine")
    return " ".join(aliases)


def enrich_species_option(option, metadata=None):
    if not isinstance(option, dict):
        return option
    enriched = dict(option)
    species_id = enriched.get("species_id", enriched.get("id"))
    species_name = enriched.get("species_name", enriched.get("species", enriched.get("name", "")))
    meta = (metadata or {}).get(str(species_id), {})
    enriched.update({
        "common_names": meta.get("common_names", ""),
        "category": meta.get("category", ""),
        "foliage_type": meta.get("foliage_type", ""),
        "origin_type": meta.get("origin_type", ""),
        "family": meta.get("family", ""),
        "image_url": meta.get("image_url", ""),
        "height_m": meta.get("height_m", ""),
        "lifespan_years": meta.get("lifespan_years", ""),
        "particularities": meta.get("particularities", ""),
        "planter_likes": meta.get("planter_likes", ""),
        "details_endpoint": meta.get("details_endpoint", ""),
        "search_aliases": species_search_aliases(species_name),
    })
    return enriched


def catalog_view_projects():
    """
    Mainnet Tree-Nation catalog viewer.
    Reads full_catalog.json only; does not call Tree-Nation and does not plant anything.
    """
    catalog = load_json(FULL_CATALOG_FILE, {}) or {}
    projects = catalog.get("projects", []) if isinstance(catalog, dict) else []

    prepared = []
    metadata = species_metadata_index()
    for project in projects:
        if not isinstance(project, dict):
            continue

        species = project.get("species", [])
        if not isinstance(species, list):
            species = []

        available_species = []
        for sp in species:
            if not isinstance(sp, dict):
                continue
            try:
                stock = float(sp.get("stock", 0) or 0)
                price = float(sp.get("price", 0) or 0)
                co2 = float(sp.get("life_time_CO2", 0) or 0)
            except Exception:
                stock = 0
                price = 0
                co2 = 0

            if stock > 0 and price > 0 and co2 >= 0:
                sp_copy = enrich_species_option(sp, metadata)
                sp_copy["co2_per_eur"] = round(co2 / price, 2) if price else 0
                available_species.append(sp_copy)

        available_species.sort(key=lambda sp: (-(sp.get("co2_per_eur") or 0), sp.get("price") or 999999))

        cheapest = min((float(sp.get("price", 0) or 0) for sp in available_species), default=None)
        max_co2 = max((float(sp.get("life_time_CO2", 0) or 0) for sp in available_species), default=None)
        best_value = max((float(sp.get("co2_per_eur", 0) or 0) for sp in available_species), default=None)

        prepared.append({
            "project_id": project.get("project_id", "—"),
            "project_name": project.get("project_name", "Unknown project"),
            "location": project.get("location", "—"),
            "species_total": project.get("species_total", len(species)),
            "species_available": project.get("species_available", len(available_species)),
            "available_species": available_species,
            "cheapest_price": cheapest,
            "max_co2": max_co2,
            "best_value": best_value,
            "has_available": len(available_species) > 0
        })

    prepared.sort(key=lambda p: (not p["has_available"], str(p["project_name"]).lower()))

    return {
        "fetched_at": catalog.get("fetched_at", "—") if isinstance(catalog, dict) else "—",
        "projects_count": catalog.get("projects_count", len(prepared)) if isinstance(catalog, dict) else len(prepared),
        "species_total": catalog.get("species_total", "—") if isinstance(catalog, dict) else "—",
        "available_species_total": catalog.get("available_species_total", "—") if isinstance(catalog, dict) else "—",
        "projects": prepared
    }



def catalog_best_value_snapshot():
    """
    Read-only quick snapshot for the catalog page.
    For common Pi amounts, show the best maximum CO2 result currently possible
    from the saved Tree-Nation catalog using current operational settings.
    No API call, no planting, no spending, no donation creation.
    """
    config = load_json(CONFIG_FILE, {}) or {}

    try:
        pi_value = float(config.get("pi_value", 0.15) or 0.15)
    except Exception:
        pi_value = 0.15

    currency = config.get("currency", "EUR")
    test_amounts = [1, 2, 3, 5, 10, 50]

    catalog = load_json(FULL_CATALOG_FILE, {}) or {}
    projects = catalog.get("projects", []) if isinstance(catalog, dict) else []

    species_options = []
    for project in projects:
        if not isinstance(project, dict):
            continue

        for sp in project.get("species", []) or []:
            if not isinstance(sp, dict):
                continue

            try:
                stock = int(float(sp.get("stock", 0) or 0))
                price = float(sp.get("price", 0) or 0)
                co2 = float(sp.get("life_time_CO2", 0) or 0)
            except Exception:
                continue

            if stock <= 0 or price <= 0 or co2 <= 0:
                continue

            species_options.append({
                "project_id": project.get("project_id"),
                "project_name": project.get("project_name", "Unknown project"),
                "location": project.get("location", "—"),
                "species_id": sp.get("id"),
                "species_name": sp.get("name", "Unknown species"),
                "price": price,
                "co2": co2,
                "stock": stock,
                "co2_per_eur": round(co2 / price, 2) if price else 0,
            })

    rows = []
    best_global_value = 0

    for amount_pi in test_amounts:
        budget = amount_pi * pi_value
        best = None

        for sp in species_options:
            max_qty_by_budget = int(budget // sp["price"])
            max_qty = min(max_qty_by_budget, sp["stock"])
            if max_qty < 1:
                continue

            total_cost = max_qty * sp["price"]
            total_co2 = max_qty * sp["co2"]
            co2_per_pi = total_co2 / amount_pi if amount_pi else 0

            candidate = dict(sp)
            candidate.update({
                "amount_pi": amount_pi,
                "budget": round(budget, 2),
                "quantity": max_qty,
                "total_cost": round(total_cost, 2),
                "total_co2": round(total_co2, 2),
                "co2_per_pi": round(co2_per_pi, 2),
                "unused_budget": round(budget - total_cost, 2),
            })

            if (
                best is None
                or candidate["total_co2"] > best["total_co2"]
                or (
                    candidate["total_co2"] == best["total_co2"]
                    and candidate["total_cost"] < best["total_cost"]
                )
            ):
                best = candidate

        if best:
            best_global_value = max(best_global_value, best.get("co2_per_eur", 0) or 0)
            rows.append(best)
        else:
            rows.append({
                "amount_pi": amount_pi,
                "budget": round(budget, 2),
                "quantity": 0,
                "total_cost": 0,
                "total_co2": 0,
                "co2_per_pi": 0,
                "unused_budget": round(budget, 2),
                "project_name": "No option found",
                "species_name": "—",
                "location": "—",
                "price": 0,
                "co2": 0,
                "co2_per_eur": 0,
            })

    viable_rows = [row for row in rows if row.get("total_co2", 0) > 0]

    if not viable_rows:
        health_level = "critical"
        health_label = "No direct catalog options"
        health_message = "No tested Pi amount can currently buy an available species from the saved catalog."
    elif len(viable_rows) < len(rows):
        health_level = "warning"
        health_label = "Partial direct options"
        health_message = "Some small Pi amounts cannot directly buy from the catalog. Pool coverage may still make this fine."
    else:
        health_level = "healthy"
        health_label = "Direct options available"
        health_message = "All tested Pi amounts have at least one current catalog option."

    return {
        "currency": currency,
        "pi_value": pi_value,
        "rows": rows,
        "best_global_value": round(best_global_value, 2),
        "available_species_checked": len(species_options),
        "health_level": health_level,
        "health_label": health_label,
        "health_message": health_message,
    }

def catalog_settings_viability():
    """
    Read-only viability check for current TPF settings against the saved catalog.
    It does not create donations, does not plant, and does not call Tree-Nation.
    A species is viable for a Pi amount if the EUR budget can buy at least one tree
    and the maximum buyable quantity reaches the required minimum CO₂.
    """
    config = load_json(CONFIG_FILE, {}) or {}

    try:
        pi_value = float(config.get("pi_value", 0.15) or 0.15)
    except Exception:
        pi_value = 0.15

    try:
        min_co2_per_pi = float(config.get("min_co2_per_pi", 30) or 30)
    except Exception:
        min_co2_per_pi = 30

    currency = config.get("currency", "EUR")
    test_amounts = [1, 2, 3, 5, 10, 50]

    catalog = load_json(FULL_CATALOG_FILE, {}) or {}
    projects = catalog.get("projects", []) if isinstance(catalog, dict) else []

    available_species = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        species_list = project.get("species", [])
        if not isinstance(species_list, list):
            continue

        for sp in species_list:
            if not isinstance(sp, dict):
                continue
            try:
                stock = int(float(sp.get("stock", 0) or 0))
                price = float(sp.get("price", 0) or 0)
                co2 = float(sp.get("life_time_CO2", 0) or 0)
            except Exception:
                continue

            if stock <= 0 or price <= 0 or co2 <= 0:
                continue

            available_species.append({
                "project_id": project.get("project_id"),
                "project_name": project.get("project_name", "Unknown project"),
                "location": project.get("location", "—"),
                "species_id": sp.get("id"),
                "species_name": sp.get("name", "Unknown species"),
                "price": price,
                "co2": co2,
                "stock": stock,
                "co2_per_eur": round(co2 / price, 2) if price else 0
            })

    checks = []
    for amount_pi in test_amounts:
        budget = amount_pi * pi_value
        required_co2 = amount_pi * min_co2_per_pi
        viable = []

        for sp in available_species:
            max_qty_by_budget = int(budget // sp["price"])
            max_qty = min(max_qty_by_budget, sp["stock"])
            if max_qty < 1:
                continue

            total_co2 = max_qty * sp["co2"]
            if total_co2 >= required_co2:
                option = dict(sp)
                option["max_qty"] = max_qty
                option["total_cost"] = round(max_qty * sp["price"], 2)
                option["total_co2"] = round(total_co2, 2)
                option["required_co2"] = round(required_co2, 2)
                viable.append(option)

        viable.sort(key=lambda item: (-item["co2_per_eur"], item["total_cost"], -item["total_co2"]))

        count = len(viable)
        if count == 0:
            level = "critical"
            label = "Not viable"
            message = "No available species can fulfill this Pi amount with the current settings."
        elif count <= 3:
            level = "warning"
            label = "Tight"
            message = "Only a few options fit. Watch this before changing public settings."
        else:
            level = "healthy"
            label = "Viable"
            message = "Enough options currently fit the settings."

        checks.append({
            "amount_pi": amount_pi,
            "budget": round(budget, 2),
            "required_co2": round(required_co2, 2),
            "viable_count": count,
            "level": level,
            "label": label,
            "message": message,
            "top_options": viable[:5]
        })

    overall_min = min((check["viable_count"] for check in checks), default=0)
    overall_zero = sum(1 for check in checks if check["viable_count"] == 0)

    if overall_zero:
        overall_level = "critical"
        overall_label = "Settings need attention"
        overall_message = "At least one common donation size has no viable catalog option."
    elif overall_min <= 3:
        overall_level = "warning"
        overall_label = "Settings are tight"
        overall_message = "All tested amounts work, but some have very few options."
    else:
        overall_level = "healthy"
        overall_label = "Settings look viable"
        overall_message = "All tested amounts have several current catalog options."

    return {
        "pi_value": pi_value,
        "min_co2_per_pi": min_co2_per_pi,
        "currency": currency,
        "available_species_checked": len(available_species),
        "overall_level": overall_level,
        "overall_label": overall_label,
        "overall_message": overall_message,
        "checks": checks
    }


@app.route("/planting/catalog")
def planting_catalog():
    catalog = catalog_status()
    catalog_view = catalog_view_projects()
    settings_data = load_operational_settings()
    viability = catalog_settings_viability()
    snapshot = catalog_best_value_snapshot()

    return render_template(
        "catalog_view.html",
        catalog=catalog,
        catalog_view=catalog_view,
        settings=settings_data,
        viability=viability,
        snapshot=snapshot
    )


@app.route("/pools")
def pools():
    pools_path = DATA_ROOT / "co2-pool" / "pools"
    pools = [item["data"] for item in load_json_files(pools_path)]
    return render_template("pools.html", pools=pools)


def _pool_has_shares(pool):
    """A historical allocation locks ownership even if today's balance is zero."""
    pool_id = pool.get("pool_id")
    for key in ("allocated_trees", "allocated_co2_kg"):
        try:
            if float(pool.get(key) or 0) != 0:
                return True
        except (TypeError, ValueError):
            return True  # Unknown balance is not safe evidence of no shares.
    for item in load_json_files(DATA_ROOT / "co2-pool" / "allocations"):
        record = item.get("data")
        if isinstance(record, dict) and record.get("pool_id") == pool_id:
            return True
        if "error" in item:
            return True  # A damaged record requires review.
    ledger_path = DATA_ROOT / "co2-pool" / "pool_ledger.json"
    ledger = load_json(ledger_path, None)
    if ledger_path.exists() and not isinstance(ledger, list):
        return True
    return any(isinstance(entry, dict) and entry.get("pool_id") == pool_id for entry in (ledger or []))


def _save_pool_correction(path, pool):
    """Replace the record and its audit event in one filesystem operation."""
    fd, temporary = tempfile.mkstemp(prefix=".pool-correction-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(pool, output, indent=2, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@app.route("/pools/<pool_id>")
def pool_detail(pool_id):
    if not re.fullmatch(r"pool_[A-Za-z0-9_-]+", pool_id):
        return "Invalid pool ID", 400
    pool_file = DATA_ROOT / "co2-pool" / "pools" / f"{pool_id}.json"
    pool = load_json(pool_file, None)
    if not isinstance(pool, dict):
        return "Pool not found", 404
    response_file = DATA_ROOT / "tree-nation" / f"{pool_id}_selected_api_response.json"
    response_data = load_json(response_file, {}) or {}
    selected_option = response_data.get("selected_option", {}) if isinstance(response_data, dict) else {}
    certificates = pool.get("certificates", [])
    if not isinstance(certificates, list):
        certificates = []
    detail = {
        "pool": pool, "selected_option": selected_option if isinstance(selected_option, dict) else {},
        "certificates": certificates, "pool_file": str(pool_file.relative_to(ROOT_DIR)),
        "response_file": str(response_file.relative_to(ROOT_DIR)) if response_file.exists() else None,
    }
    owner_partner = _read_partner(pool.get("owner_partner_id")) if pool.get("owner_kind") == "partner" else None
    return render_template("pool_detail.html", detail=detail, owner_partner=owner_partner,
                           owner_editable=pool.get("pool_availability") == "dedicated" and not _pool_has_shares(pool),
                           partners=_all_partners())


@app.route("/pools/<pool_id>/correct-setup", methods=["POST"])
def pool_correct_setup(pool_id):
    """Record a local setup correction; never change a used pool's owner."""
    if not re.fullmatch(r"pool_[A-Za-z0-9_-]+", pool_id):
        return "Invalid pool ID", 400
    pool_file = DATA_ROOT / "co2-pool" / "pools" / (pool_id + ".json")
    pool = load_json(pool_file, None)
    if not isinstance(pool, dict) or pool.get("pool_id") != pool_id:
        return "Pool not found", 404
    if pool.get("pool_availability") != "dedicated":
        return "Only dedicated pools have an owner to correct here.", 409
    reason = request.form.get("reason", "").strip()
    if not reason or len(reason) > 1000:
        return "Enter a short reason for this correction.", 400
    if request.form.get("confirm_pool_id", "").strip() != pool_id:
        return "Type the pool ID to confirm. Nothing was saved.", 400
    name = request.form.get("pool_name", "").strip()
    if not name or len(name) > 200:
        return "Enter a pool name (up to 200 characters).", 400
    previous_name = str(pool.get("name") or "").strip()
    if name != previous_name:
        for entry in load_json_files(DATA_ROOT / "co2-pool" / "pools"):
            other = entry.get("data")
            if isinstance(other, dict) and other.get("pool_id") != pool_id and str(other.get("name") or "").strip().casefold() == name.casefold():
                return "Another pool already has that name.", 409
    try:
        kind, partner_id = _validated_pool_owner("dedicated", request.form.get("owner_kind"), request.form.get("owner_partner_id"))
    except ValueError as exc:
        return str(exc), 400
    previous_owner = (pool.get("owner_kind") or "", pool.get("owner_partner_id") or "")
    next_owner = (kind, partner_id or "")
    owner_changed = previous_owner != next_owner
    name_changed = previous_name != name
    if not owner_changed and not name_changed:
        return "Nothing changed. No correction was recorded.", 400
    if owner_changed and _pool_has_shares(pool):
        return "This pool has share records. Its owner is locked; review a separate documented correction.", 409
    old_links = [item["id"] for item in _all_partners() if pool_id in item.get("pool_ids", [])]
    if owner_changed and old_links and (len(old_links) != 1 or kind != "partner" or partner_id != old_links[0]):
        return "An older partner link conflicts with this owner. Review that record first.", 409
    at = now_iso()
    if owner_changed:
        pool["owner_kind"] = kind
        pool["owner_partner_id"] = partner_id
        pool.setdefault("ownership_history", []).append({
            "at": at, "action": "owner_corrected" if previous_owner[0] else "legacy_owner_assigned",
            "from": {"owner_kind": previous_owner[0], "partner_id": previous_owner[1]},
            "to": {"owner_kind": kind, "partner_id": partner_id},
            "reason": reason, "source": "local_tpf_admin",
        })
    if name_changed:
        pool["name"] = name
        pool.setdefault("setup_history", []).append({
            "at": at, "action": "display_name_corrected", "from": previous_name,
            "to": name, "reason": reason, "source": "local_tpf_admin",
        })
    _save_pool_correction(pool_file, pool)
    return redirect(url_for("pool_detail", pool_id=pool_id))



@app.route("/donations")
def donations():
    items = build_donation_flow_items()
    return render_template("donations.html", items=items)


@app.route("/records")
def records():
    items = build_donation_flow_items()
    return render_template("donations.html", items=items)


@app.route("/settings", methods=["GET"])
def settings():
    settings_data = load_operational_settings()
    return render_template("settings.html", settings=settings_data, result=None)


@app.route("/pricing/partner-pools", methods=["GET"])
def partner_pool_pricing():
    """Explore prices; only explicit Save offer writes a draft."""
    return render_template("partner_pool_pricing.html", **partner_pool_context(request.args))


def partner_pool_context(params):
    """Recompute choices on every request; never trust prices submitted by a browser."""
    settings_data = load_operational_settings()
    mode = params.get("mode", "target")
    basis = params.get("basis", "co2")
    temporary_addition = params.get("test_addition", "").strip()
    addition = temporary_addition or settings_data["tpf_addition_percent"]
    discount = params.get("partner_discount", "0")
    target_co2 = params.get("target_co2", "2000")
    target_trees = params.get("target_trees", "20")
    budget_pi = params.get("budget_pi", "120")
    value = budget_pi if mode == "budget" else (target_trees if basis == "trees" else target_co2)
    search = params.get("search", "").strip()
    selected_category = params.get("tree_category", "").strip()
    selected_theme = params.get("project_theme", "").strip()
    offer_name = params.get("offer_name", "").strip()[:120]
    show_all = params.get("show") == "all"
    sort_by = "price" if mode == "target" else "allocation"
    rows, total, error, suggestions = [], 0, None, []
    catalog = load_json(FULL_CATALOG_FILE, {}) or {}
    theme_data = load_json(Path(__file__).with_name("pricing_project_themes.json"), {}) or {}
    project_themes = theme_data.get("projects", {})
    available_ids = {str(p.get("project_id")) for p in catalog.get("projects", []) if p.get("species_available")}
    themes = [(key, info) for key, info in theme_data.get("themes", {}).items()
              if any(pid in available_ids and (key in project.get("theme_ids", []) or
                         set(project.get("benefits", [])) & set(info["benefits"]))
                     for pid, project in project_themes.items())]
    selected_theme_label = theme_data.get("themes", {}).get(selected_theme, {}).get("label")
    category_by_species = {}
    for project in catalog.get("projects", []):
        for species in project.get("species", []):
            try:
                in_stock = int(species.get("stock") or 0) > 0
            except (ValueError, TypeError):
                in_stock = False
            if not in_stock:
                continue
            sid = str(species.get("id") or "")
            if not sid:
                continue
            detail = load_json(DATA_ROOT / "project-intelligence" / "species" / f"species_{sid}.json", {}) or {}
            metadata = detail.get("tree_nation") or {}
            category = metadata.get("category") or {}
            category = category.get("name") if isinstance(category, dict) else None
            if category and str(detail.get("project_id")) == str(project.get("project_id")):
                category_by_species[sid] = category
    categories = sorted(set(category_by_species.values()), key=str.casefold)
    if settings_data["currency"] != "EUR":
        error = "Tree-Nation catalogue costs are in EUR. Set the planning currency to EUR before using this calculator."
    elif not catalog.get("projects"):
        error = "Mainnet Tree-Nation catalogue unavailable. Refresh the catalogue before calculating."
    else:
        try:
            common = dict(basis=basis, addition_percent=addition, discount_percent=discount,
                          eur_per_pi=settings_data["pi_value"],
                          minimum_co2_per_pi=settings_data["min_co2_per_pi"], limit=None)
            if mode == "target":
                rows, total = catalog_choices(catalog, target=value, **common)
            elif mode == "budget":
                rows, total = budget_choices(catalog, pi_budget=value, **common)
            else:
                raise ValueError("Choose a calculation direction")
            if selected_category:
                rows = [row for row in rows if category_by_species.get(str(row["species_id"])) == selected_category]
            if selected_theme:
                benefits = set(theme_data.get("themes", {}).get(selected_theme, {}).get("benefits", []))
                rows = [row for row in rows if selected_theme in project_themes.get(str(row["project_id"]), {}).get("theme_ids", []) or
                        benefits & set(project_themes.get(str(row["project_id"]), {}).get("benefits", []))]
            # Suggest only names with an actual result for these filters and current stock.
            suggestions = sorted({name for row in rows for name in (row["project"], row["species"]) if name}, key=str.casefold)
            if search:
                rows = [row for row in rows if search.casefold() in (row["project"] + " " + row["species"]).casefold()]
            rows = sort_choices(rows, sort_by, basis)
            for row in rows:
                project_id = str(row["project_id"])
                verified_project = project_themes.get(project_id, {})
                row["tree_category"] = category_by_species.get(str(row["species_id"]))
                row["project_benefits"] = verified_project.get("benefits", [])
                row["project_note"] = verified_project.get("note", "")
                row["project_benefit_source"] = verified_project.get("source_url", "")
                row["project_source_type"] = verified_project.get("source_type", "checked_page")
            total = len(rows)
            if not show_all:
                rows = rows[:20]
        except (ValueError, TypeError) as exc:
            error = str(exc)
    offer_params = {key: params.get(key, "") for key in
                    ("offer_name", "mode", "basis", "target_co2", "target_trees", "budget_pi",
                     "test_addition", "partner_discount", "tree_category", "project_theme", "search")}
    return dict(rows=rows, total=total, offer_name=offer_name, offer_params=offer_params,
                           error=error, settings=settings_data, mode=mode, basis=basis,
                           target_co2=target_co2, target_trees=target_trees, budget_pi=budget_pi,
                           temporary_addition=temporary_addition, addition=addition,
                           discount=discount, search=search, suggestions=suggestions,
                           categories=categories, themes=themes,
                           selected_category=selected_category, selected_theme=selected_theme,
                           selected_theme_label=selected_theme_label,
                           show_all=show_all,
                           all_choices_url=url_for("partner_pool_pricing", **dict(params, show="all")))


PARTNER_OFFERS_DIR = DATA_ROOT / "partner-offers"
# Review snapshots are signed by this running admin process. Saving an offer
# preserves the reviewed figures; it never trusts unsigned browser prices.
_OFFER_REVIEW_SIGNER = URLSafeSerializer(os.urandom(32), salt="tpf-offer-review-v1")


def suggest_budget_offer_rows(rows, basis):
    """Use the entered Pi for the most backing, offering different projects."""
    ordered = sort_choices(rows, "allocation", basis)
    selected, used_keys, used_projects = [], set(), set()
    # First take the best matching choice from each project. If filters leave
    # fewer than three projects, fill with other species from those projects.
    for fresh_project in (True, False):
        for row in ordered:
            key = (str(row["project_id"]), str(row["species_id"]))
            project = str(row["project_id"])
            if key in used_keys or (fresh_project and project in used_projects):
                continue
            selected.append((row, "Suggested"))
            used_keys.add(key)
            used_projects.add(project)
            if len(selected) == 3:
                return selected
    return selected


def offer_choice_snapshot(row, source):
    """Freeze numbers and provenance used for a proposed choice."""
    common_name = pool_species_metadata(row["species_id"]).get("common_name_en", "")
    common_name = common_name.split(";")[0].split(",")[0].strip()
    return {
        "key": f'{row["project_id"]}:{row["species_id"]}',
        "source": source,
        "project_id": row["project_id"], "project": row["project"],
        "species_id": row["species_id"], "species": row["species"],
        "common_name": common_name,
        "trees": row["trees"], "co2_kg": row["co2_kg"],
        "tree_category": row.get("tree_category"),
        "project_note": row.get("project_note", ""),
        "project_benefits": row.get("project_benefits", []),
        "project_benefit_source": row.get("project_benefit_source", ""),
        "partner_price_pi": row["pricing"]["pi_cent_ceiling_preview"],
        "planting_cost_eur": row["pricing"]["planting_cost_eur"],
        "pricing": row["pricing"],
    }


def suggest_offer_rows(rows, selected):
    """Suggest distinct projects across the price range; keep all manual picks."""
    ordered = sorted(rows, key=lambda r: (float(r["pricing"]["pi_cent_ceiling_preview"]), str(r["project_id"])))
    if not ordered or len(selected) >= 4:
        return []
    used_keys = {f'{r["project_id"]}:{r["species_id"]}' for r in selected}
    used_projects = {str(r["project_id"]) for r in selected}
    # A practical low-price reference, without automatically picking the absolute cheapest.
    # Stay within the practical lower-to-middle range: the most expensive
    # catalogue entries can be many times dearer without offering more backing.
    positions = (("Lower price", 0.12, 0.02, 0.19),
                 ("Middle price", 0.32, 0.19, 0.43),
                 ("Higher price", 0.55, 0.43, 0.63))
    if len(selected) == 2:
        positions = (positions[0], positions[2])
    elif len(selected) == 3:
        lower_cutoff = float(ordered[round((len(ordered) - 1) * 0.19)]["pricing"]["pi_cent_ceiling_preview"])
        positions = (positions[2],) if any(float(row["pricing"]["pi_cent_ceiling_preview"]) <= lower_cutoff for row in selected) else (positions[0],)
    suggestions = []
    for label, fraction, left, right in positions:
        if len(selected) + len(suggestions) >= 4:
            break
        anchor = round((len(ordered) - 1) * fraction)
        candidates = sorted((i for i in range(len(ordered)) if left <= i / max(1, len(ordered) - 1) <= right),
                            key=lambda n: abs(n - anchor))
        for fresh_project in (True, False):
            found = next((ordered[i] for i in candidates
                          if f'{ordered[i]["project_id"]}:{ordered[i]["species_id"]}' not in used_keys
                          and all(abs(float(ordered[i]["pricing"]["pi_cent_ceiling_preview"]) - float(other["pricing"]["pi_cent_ceiling_preview"])) >= 0.05 * max(1, float(other["pricing"]["pi_cent_ceiling_preview"])) for other in selected + [r for r, _ in suggestions])
                          and (not fresh_project or str(ordered[i]["project_id"]) not in used_projects)), None)
            if found:
                key = f'{found["project_id"]}:{found["species_id"]}'
                used_keys.add(key)
                used_projects.add(str(found["project_id"]))
                suggestions.append((found, label))
                break
    # Narrow price bands or a small filtered result set may have no candidate.
    # Fill the comparison from the remaining matching choices, preferring
    # different projects while keeping all explicitly selected choices.
    target_count = min(len(ordered), 3 if not selected else 4)
    for fraction in (0.12, 0.50, 0.85, 0.32, 0.68):
        if len(selected) + len(suggestions) >= target_count:
            break
        anchor = round((len(ordered) - 1) * fraction)
        candidates = sorted(range(len(ordered)), key=lambda i: abs(i - anchor))
        for fresh_project in (True, False):
            found = next((ordered[i] for i in candidates
                          if f'{ordered[i]["project_id"]}:{ordered[i]["species_id"]}' not in used_keys
                          and (not fresh_project or str(ordered[i]["project_id"]) not in used_projects)), None)
            if found:
                key = f'{found["project_id"]}:{found["species_id"]}'
                used_keys.add(key)
                used_projects.add(str(found["project_id"]))
                suggestions.append((found, "Additional option"))
                break
    return suggestions


@app.route("/pricing/partner-pools/offer/preview", methods=["POST"])
def preview_partner_offer():
    params = request.form.to_dict(flat=True)
    params["show"] = "all"
    context = partner_pool_context(params)
    if context["error"]:
        return render_template("partner_pool_pricing.html", **context), 400
    name = request.form.get("offer_name", "").strip()[:120]
    if not name:
        context["error"] = "Give the offer a name first, such as GPM Tree Pool Offer."
        return render_template("partner_pool_pricing.html", **context), 400
    rows = context["rows"]
    by_key = {f'{row["project_id"]}:{row["species_id"]}': row for row in rows}
    chosen = list(dict.fromkeys(request.form.getlist("include")))
    if len(chosen) > 500 or any(key not in by_key for key in chosen):
        context["error"] = "An included choice no longer fits these inputs or current stock. Review the updated choices below and build the offer again."
        return render_template("partner_pool_pricing.html", **context), 400
    manual = [by_key[key] for key in chosen]
    suggested = (suggest_budget_offer_rows(rows, context["basis"])
                 if context["mode"] == "budget" else suggest_offer_rows(rows, []))
    # Always retain the automatic comparison, plus every manual selection.
    # A manually selected automatic option appears once, marked as included.
    selected_by_key = {f'{row["project_id"]}:{row["species_id"]}': (row, source)
                       for row, source in suggested}
    for row in manual:
        selected_by_key[f'{row["project_id"]}:{row["species_id"]}'] = (row, "You included")
    ordered = sort_choices([row for row, _ in selected_by_key.values()],
                           "allocation" if context["mode"] == "budget" else "price", context["basis"])
    selected = [(row, selected_by_key[f'{row["project_id"]}:{row["species_id"]}'][1])
                for row in ordered]
    if not selected:
        return "No planting choices fit this offer. Please change the search.", 400
    choices = [offer_choice_snapshot(row, source) for row, source in selected]
    # Keep effective values, including defaults, in the reviewed snapshot.
    frozen_params = dict(context["offer_params"], offer_name=name, mode=context["mode"],
                         basis=context["basis"], budget_pi=context["budget_pi"],
                         target_co2=context["target_co2"], target_trees=context["target_trees"],
                         test_addition=context["addition"], partner_discount=context["discount"])
    snapshot = {
        "name": name, "choices": choices, "search": frozen_params,
        "catalog_fetched_at": (load_json(FULL_CATALOG_FILE, {}) or {}).get("fetched_at"),
        "pricing_settings": {"eur_per_pi": context["settings"]["pi_value"],
                             "tpf_addition_percent": context["addition"],
                             "partner_discount_percent": context["discount"]},
    }
    return render_template("partner_offer_review.html", name=name, choices=choices,
                           params=frozen_params, settings=context["settings"],
                           review_token=_OFFER_REVIEW_SIGNER.dumps(snapshot),
                           catalog_fetched_at=snapshot["catalog_fetched_at"],
                           too_many=len(choices) > 4, matching_count=len(rows))


def _save_partner_offer(record):
    """Create one complete file without touching existing pool or donation data."""
    PARTNER_OFFERS_DIR.mkdir(parents=True, exist_ok=True)
    destination = PARTNER_OFFERS_DIR / (record["id"] + ".json")
    fd, temp_name = tempfile.mkstemp(prefix=".offer-", suffix=".tmp", dir=PARTNER_OFFERS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@app.route("/pricing/partner-pools/offers", methods=["GET"])
def saved_partner_offers():
    offers = [entry["data"] for entry in load_json_files(PARTNER_OFFERS_DIR)
              if isinstance(entry.get("data"), dict) and entry["data"].get("schema") == "tpf_partner_offer_v1"]
    offers.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return render_template("partner_offers.html", offers=offers)


@app.route("/pricing/partner-pools/offers/<offer_id>/delete", methods=["POST"])
def delete_partner_offer(offer_id):
    """Remove an offer from the active list, retaining its original JSON for recovery."""
    offer = _read_partner_offer(offer_id)
    if offer is None:
        return "Offer not found", 404
    if request.form.get("confirm_offer_id") != offer_id:
        return "Deletion was not confirmed", 400
    source = PARTNER_OFFERS_DIR / (offer_id + ".json")
    removed_dir = DATA_ROOT / "partner-offers-removed"
    removed_dir.mkdir(parents=True, exist_ok=True)
    destination = removed_dir / (offer_id + "-" + uuid4().hex + ".json")
    os.replace(source, destination)
    return redirect(url_for("saved_partner_offers", deleted="1"))


def _read_partner_offer(offer_id):
    if not re.fullmatch(r"[a-f0-9]{32}", offer_id):
        return None
    record = load_json(PARTNER_OFFERS_DIR / (offer_id + ".json"), None)
    if not isinstance(record, dict) or record.get("schema") != "tpf_partner_offer_v1" or record.get("id") != offer_id:
        return None
    # Older saved offers remain unchanged on disk; show cached common names when available.
    for choice in record.get("choices", []):
        if isinstance(choice, dict) and "common_name" not in choice and choice.get("species_id"):
            value = pool_species_metadata(choice["species_id"]).get("common_name_en", "")
            choice["common_name"] = value.split(";")[0].split(",")[0].strip()
    return record


@app.route("/pricing/partner-pools/offers/save", methods=["POST"])
def save_partner_offer():
    """Save exactly the signed review snapshot and the retained options."""
    try:
        snapshot = _OFFER_REVIEW_SIGNER.loads(request.form.get("review_token", ""))
    except BadData:
        return ('This review is no longer available. <a href="' +
                url_for("partner_pool_pricing") + '">Return to the calculator</a> and build the offer again.', 400)
    by_key = {choice["key"]: choice for choice in snapshot["choices"]}
    keys = list(dict.fromkeys(request.form.getlist("keep")))
    if not keys or any(key not in by_key for key in keys):
        return "Keep at least one of the reviewed choices before saving.", 400
    # Retain review order even if form fields arrive in another order.
    kept = set(keys)
    choices = [choice for choice in snapshot["choices"] if choice["key"] in kept]
    record = {
        "schema": "tpf_partner_offer_v1", "id": uuid4().hex,
        "created_at": now_iso(), "name": snapshot["name"], "status": "ready",
        "chosen_key": None, "choices": choices,
        "search": snapshot["search"],
        "catalog_fetched_at": snapshot["catalog_fetched_at"],
        "pricing_settings": snapshot["pricing_settings"],
    }
    _save_partner_offer(record)
    return redirect(url_for("present_partner_offer", offer_id=record["id"]))


@app.route("/pricing/partner-pools/offers/<offer_id>", methods=["GET"])
def partner_offer_detail(offer_id):
    offer = _read_partner_offer(offer_id)
    if offer is None:
        return "Offer not found", 404
    return render_template("partner_offer_detail.html", offer=offer)


@app.route("/pricing/partner-pools/offers/<offer_id>/present", methods=["GET"])
def present_partner_offer(offer_id):
    offer = _read_partner_offer(offer_id)
    if offer is None:
        return "Offer not found", 404
    return render_template("partner_offer_present.html", offer=offer)


@app.route("/pricing/partner-pools/offers/<offer_id>/choose", methods=["POST"])
def choose_partner_offer_option(offer_id):
    offer = _read_partner_offer(offer_id)
    if offer is None:
        return "Offer not found", 404
    if offer.get("status") == "accepted":
        return "This offer is accepted. Start a new calculation to propose another choice.", 409
    selected = request.form.get("choice", "")
    if selected not in [item.get("key") for item in offer["choices"]]:
        return "Choose one of the saved options.", 400
    offer["chosen_key"] = selected
    offer["status"] = "option_chosen"
    offer.pop("accepted_at", None)
    _save_partner_offer(offer)
    return redirect(url_for("partner_offer_detail", offer_id=offer_id))


@app.route("/pricing/partner-pools/offers/<offer_id>/accept", methods=["POST"])
def accept_partner_offer(offer_id):
    offer = _read_partner_offer(offer_id)
    if offer is None:
        return "Offer not found", 404
    if not offer.get("chosen_key") or offer["chosen_key"] not in [c.get("key") for c in offer["choices"]]:
        return "Choose a saved option first.", 400
    offer["status"] = "accepted"
    offer["accepted_at"] = now_iso()
    _save_partner_offer(offer)
    return redirect(url_for("partner_offer_detail", offer_id=offer_id))


@app.route("/settings/update", methods=["POST"])
def update_settings():
    result = save_operational_settings(request.form)
    settings_data = load_operational_settings()
    return render_template("settings.html", settings=settings_data, result=result)



def extract_message_from_json(data):
    """Best-effort extractor for the public Tree-Nation message stored in TPF files."""
    if not isinstance(data, dict):
        return ""

    candidates = [
        data.get("tree_nation_message"),
        data.get("public_message"),
        data.get("message"),
    ]

    tree_nation = data.get("tree_nation", {}) if isinstance(data.get("tree_nation", {}), dict) else {}
    candidates.extend([
        tree_nation.get("message"),
        tree_nation.get("tree_nation_message"),
    ])

    request_data = data.get("request", {}) if isinstance(data.get("request", {}), dict) else {}
    payload = request_data.get("payload", {}) if isinstance(request_data.get("payload", {}), dict) else {}
    candidates.append(payload.get("message"))

    raw_request = data.get("raw_request", {}) if isinstance(data.get("raw_request", {}), dict) else {}
    raw_payload = raw_request.get("payload", {}) if isinstance(raw_request.get("payload", {}), dict) else {}
    candidates.append(raw_payload.get("message"))

    for value in candidates:
        value = str(value or "").strip()
        if value:
            return value
    return ""


def tree_nation_message_for_donation(donation_id):
    """Return the latest public Tree-Nation message stored for a donation.

    Completed donations should show what was actually sent or stored, not a fresh
    editable draft. This helper searches decisions, plantings and Tree-Nation
    response files and returns the newest matching message it can find.
    """
    if not donation_id:
        return None

    folders = [
        DATA_ROOT / "plantings",
        DATA_ROOT / "decisions",
        DATA_ROOT / "tree-nation",
    ]

    matches = []
    for folder in folders:
        for item in load_json_files(folder):
            file_name = item.get("file", "")
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue

            donation = data.get("donation", {}) if isinstance(data.get("donation", {}), dict) else {}
            found = (
                donation_id in file_name
                or data.get("donation_id") == donation_id
                or donation.get("donation_id") == donation_id
            )
            if not found:
                continue

            message = extract_message_from_json(data)
            if message:
                matches.append({
                    "message": message,
                    "file": file_name,
                    "modified": item.get("modified", 0),
                })

    if not matches:
        return None

    matches.sort(key=lambda item: item.get("modified", 0), reverse=True)
    return matches[0]


def files_related_to_donation(donation_id):
    """
    Human-readable file trail for one donation.
    This is used by the Records detail page.
    """
    related = []

    folders = [
        ("Pending donation input", DATA_ROOT / "donations" / "pending"),
        ("Processed donation result", DATA_ROOT / "donations" / "processed"),
        ("Archived input", DATA_ROOT / "donations" / "processed_input"),
        ("Project suggestions", DATA_ROOT / "suggestions"),
        ("Planting confirmation", DATA_ROOT / "decisions"),
        ("Planting record", DATA_ROOT / "plantings"),
        ("Shared CO₂ allocation", DATA_ROOT / "co2-pool" / "allocations"),
        ("Tree-Nation response", DATA_ROOT / "tree-nation"),
    ]

    for label, folder in folders:
        for item in load_json_files(folder):
            file_name = item.get("file", "")
            data = item.get("data", {})

            found = donation_id in file_name

            if isinstance(data, dict):
                donation = data.get("donation", {}) if isinstance(data.get("donation", {}), dict) else {}

                if data.get("donation_id") == donation_id:
                    found = True
                if donation.get("donation_id") == donation_id:
                    found = True

            if found:
                related.append({
                    "label": label,
                    "file": file_name,
                    "path": item.get("path"),
                    "modified": datetime.fromtimestamp(item.get("modified", 0), UTC).strftime("%Y-%m-%d %H:%M UTC") if item.get("modified") else "—"
                })

    return related



# ---------------------------------------------------------------------------
# Tree-Nation proof links
# ---------------------------------------------------------------------------

def project_intelligence_trees_dir():
    return DATA_ROOT / "project-intelligence" / "trees"


def _tn_norm(value):
    return str(value or "").strip().casefold()


def _tn_decision_name(value):
    if not value:
        return ""
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _tn_donation_from_decision(value):
    name = _tn_decision_name(value)
    if not name:
        return ""
    data = load_json(DATA_ROOT / "decisions" / name, {}) or {}
    if not isinstance(data, dict):
        return ""
    donation = data.get("donation", {}) if isinstance(data.get("donation"), dict) else {}
    return str(data.get("donation_id") or donation.get("donation_id") or "").strip()


def _tn_make_proof(tree, quantity=None, payment_id=None, source_file=None, donation_id=None):
    if not isinstance(tree, dict):
        return None
    tree_id = tree.get("tree_id") or tree.get("id")
    token = tree.get("tree_token") or tree.get("token")
    tree_url = tree.get("tree_url") or (f"https://tree-nation.com/trees/{tree_id}/view" if tree_id else None)
    certificate_url = tree.get("certificate_url") or (f"https://tree-nation.com/certificate/{token}" if token else None)
    co2_per_tree = tree.get("species_life_time_co2_kg")
    if co2_per_tree is None:
        co2_per_tree = tree.get("species_life_time_CO2")
    qty = quantity or tree.get("quantity")
    total_co2 = None
    try:
        total_co2 = float(co2_per_tree) * int(qty or 1)
        if total_co2.is_integer(): total_co2 = int(total_co2)
    except Exception:
        total_co2 = co2_per_tree
    return {
        "donation_id": donation_id,
        "tree_id": tree_id,
        "tree_url": tree_url,
        "certificate_url": certificate_url,
        "collect_url": tree.get("collect_url"),
        "project_id": tree.get("project_id"),
        "project_name": tree.get("project_name"),
        "species_id": tree.get("species_id"),
        "species_name": tree.get("species_name"),
        "quantity": qty,
        "total_co2_kg": total_co2,
        "payment_id": payment_id or tree.get("payment_id"),
        "source_file": source_file or tree.get("source_file"),
    }


def tree_nation_proofs_for_donation(donation_id):
    wanted = _tn_norm(donation_id)
    if not wanted:
        return []
    proofs, seen = [], set()
    def add(proof):
        if not isinstance(proof, dict): return
        if not proof.get("tree_url") and not proof.get("certificate_url"): return
        key = (str(proof.get("tree_id") or ""), str(proof.get("tree_url") or ""), str(proof.get("certificate_url") or ""))
        if key in seen: return
        seen.add(key); proofs.append(proof)

    # Primary source: canonical Project Intelligence.
    for item in load_json_files(project_intelligence_trees_dir()):
        data = item.get("data", {})
        if not isinstance(data, dict): continue
        resolved = str(data.get("donation_id") or "").strip() or _tn_donation_from_decision(data.get("decision_file"))
        if _tn_norm(resolved) != wanted: continue
        add(_tn_make_proof(data, quantity=data.get("quantity"), payment_id=data.get("payment_id"), source_file=data.get("source_file") or item.get("file"), donation_id=resolved))

    # Independent fallback: raw successful Tree-Nation responses.
    for item in load_json_files(DATA_ROOT / "tree-nation"):
        data = item.get("data", {})
        if not isinstance(data, dict): continue
        resolved = _tn_donation_from_decision(data.get("decision_file"))
        if not resolved:
            donation = data.get("donation", {}) if isinstance(data.get("donation"), dict) else {}
            resolved = str(data.get("donation_id") or donation.get("donation_id") or "").strip()
        if _tn_norm(resolved) != wanted: continue
        request_data = data.get("request", {}) if isinstance(data.get("request"), dict) else {}
        payload = request_data.get("payload", {}) if isinstance(request_data.get("payload"), dict) else {}
        response = data.get("response", {}) if isinstance(data.get("response"), dict) else {}
        response_json = response.get("json", {}) if isinstance(response.get("json"), dict) else {}
        trees = response_json.get("trees", []) if isinstance(response_json.get("trees", []), list) else []
        for tree in trees:
            add(_tn_make_proof(tree, quantity=payload.get("quantity"), payment_id=response_json.get("payment_id"), source_file=item.get("file"), donation_id=resolved))
    proofs.sort(key=lambda x: str(x.get("tree_id") or ""))
    return proofs


def shared_pool_backing_for_donation(donation_id):
    """Follow the recorded allocation to its pool, never infer a pool by amount."""
    matches = [entry.get("data") for entry in load_json_files(DATA_ROOT / "co2-pool" / "allocations")
               if isinstance(entry.get("data"), dict) and entry["data"].get("donation_id") == donation_id]
    if len(matches) != 1:
        return None
    allocation = matches[0]
    pool_id = allocation.get("pool_id", "")
    if not re.fullmatch(r"pool_[A-Za-z0-9_-]+", pool_id):
        return None
    pool = load_json(DATA_ROOT / "co2-pool" / "pools" / (pool_id + ".json"), None)
    if not isinstance(pool, dict) or pool.get("pool_id") != pool_id:
        return None
    if pool.get("pool_availability", pool.get("availability", "shared")) != "shared":
        return None
    certificates = pool.get("certificates") or []
    certificate = certificates[0] if certificates and isinstance(certificates[0], dict) else {}
    url = certificate.get("certificate_url") or pool.get("certificate_url")
    if not isinstance(url, str) or not url.startswith("https://tree-nation.com/certificate/"):
        return None
    return {"pool_id": pool_id, "pool_name": pool.get("name", pool_id),
            "co2_kg": allocation.get("co2_allocated_kg"), "certificate_url": url}


@app.route("/record/<donation_id>")
def record_detail(donation_id):
    items = build_donation_flow_items()
    record = None

    for item in items:
        if item.get("donation_id") == donation_id:
            record = item
            break

    if not record:
        return workflow_stop_page(
            "Record not found",
            f"No record found for donation ID: <b>{donation_id}</b>",
            primary_link="/records",
            primary_label="Back to Records"
        )

    related_files = files_related_to_donation(donation_id)
    project_selection = suggestion_item_for_donation(donation_id)
    if project_selection and isinstance(project_selection.get("options_flat"), list):
        metadata = species_metadata_index()
        project_selection["options_flat"] = [
            enrich_species_option(option, metadata) for option in project_selection.get("options_flat", [])
        ]

        # Keep normal valid suggestions as the default list, but also expose the
        # generator's below-minimum options for explicit donor-choice searches.
        # These exception options stay hidden until the operator actually searches.
        raw_invalid = project_selection.get("data", {}).get("invalid_options", [])
        project_selection["exception_options"] = [
            enrich_species_option(option, metadata) for option in normalize_options(raw_invalid)
        ]
    current_config = load_json(CONFIG_FILE, {}) or {}
    direct_settings_state = None
    if project_selection:
        suggestion_data = project_selection.get("data", {}) if isinstance(project_selection.get("data", {}), dict) else {}
        snapshot = suggestion_data.get("config_snapshot", {}) if isinstance(suggestion_data.get("config_snapshot", {}), dict) else {}
        try:
            current_pi_value = float(current_config.get("pi_value", 0) or 0)
        except Exception:
            current_pi_value = 0.0
        try:
            current_min_co2 = float(current_config.get("min_co2_per_pi", 30) or 30)
        except Exception:
            current_min_co2 = 30.0
        try:
            amount_pi = float(record.get("amount_pi", 0) or 0)
        except Exception:
            amount_pi = 0.0
        try:
            snapshot_pi_value = float(snapshot.get("pi_value"))
        except Exception:
            snapshot_pi_value = None
        try:
            snapshot_min_co2 = float(snapshot.get("min_co2_per_pi"))
        except Exception:
            snapshot_min_co2 = None
        direct_settings_state = {
            "snapshot_pi_value": snapshot_pi_value,
            "snapshot_min_co2_per_pi": snapshot_min_co2,
            "snapshot_budget": suggestion_data.get("budget"),
            "snapshot_required_co2": suggestion_data.get("required_co2_kg"),
            "current_pi_value": current_pi_value,
            "current_min_co2_per_pi": current_min_co2,
            "current_budget": round(amount_pi * current_pi_value, 2),
            "current_required_co2": round(amount_pi * current_min_co2, 2),
            "mismatch": (snapshot_pi_value is not None and abs(snapshot_pi_value-current_pi_value) > 1e-9) or (snapshot_min_co2 is not None and abs(snapshot_min_co2-current_min_co2) > 1e-9),
        }

    tree_nation_message_sent = tree_nation_message_for_donation(donation_id)
    tree_nation_proofs = tree_nation_proofs_for_donation(donation_id)
    shared_pool_backing = shared_pool_backing_for_donation(donation_id) if record.get("status") == "covered_by_pool" else None

    return render_template(
        "record_detail.html",
        record=record,
        related_files=related_files,
        project_selection=project_selection,
        direct_planting_config=current_config,
        direct_settings_state=direct_settings_state,
        tree_nation_message_sent=tree_nation_message_sent,
        tree_nation_proofs=tree_nation_proofs,
        shared_pool_backing=shared_pool_backing
    )



@app.route("/record/<donation_id>/regenerate_suggestions", methods=["POST"])
def regenerate_record_suggestions(donation_id):
    # Safe refresh for an unplanted Direct Planting donation. Historical suggestion
    # files are retained; a new snapshot is written using current Settings.
    lock = direct_planting_locked_for_donation(donation_id)
    if lock.get("locked"):
        return workflow_stop_page(
            "Project option refresh stopped",
            escape(lock.get("reason") or "This donation can no longer be refreshed."),
            primary_link=f"/record/{donation_id}",
            primary_label="Back to Donation Record"
        )

    existing = suggestion_item_for_donation(donation_id)
    if not existing:
        return workflow_stop_page(
            "Project option refresh stopped",
            "No existing Direct Planting suggestion snapshot was found for this donation.",
            primary_link=f"/record/{donation_id}",
            primary_label="Back to Donation Record"
        )

    data = existing.get("data", {}) if isinstance(existing.get("data", {}), dict) else {}
    donation = data.get("donation", {}) if isinstance(data.get("donation", {}), dict) else {}
    if not donation or donation.get("donation_id") != donation_id:
        return workflow_stop_page(
            "Project option refresh stopped",
            "The saved donation snapshot could not be verified. No files were changed.",
            primary_link=f"/record/{donation_id}",
            primary_label="Back to Donation Record"
        )

    try:
        import importlib.util
        module_path = SCRIPTS_DIR / "suggest_projects.py"
        spec = importlib.util.spec_from_file_location("tpf_suggest_projects", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        catalog = load_json(FULL_CATALOG_FILE, {}) or load_json(CATALOG_FILE, {}) or {}
        config = load_json(CONFIG_FILE, {}) or {}
        result = module.build_suggestions(catalog, config, donation)
        if result.get("route") != "direct_planting_suggestions":
            raise ValueError("Current settings no longer route this donation to Direct Planting.")
        suggestions_dir = DATA_ROOT / "suggestions"
        suggestions_dir.mkdir(parents=True, exist_ok=True)
        output = suggestions_dir / f"suggestion_{donation_id}_{int(time.time())}.json"
        save_json(output, result)
    except Exception as exc:
        return workflow_stop_page(
            "Project option refresh failed",
            f"No existing suggestion was overwritten. Error: {escape(str(exc))}",
            primary_link=f"/record/{donation_id}",
            primary_label="Back to Donation Record"
        )

    return redirect(f"/record/{donation_id}")


@app.route("/record/<donation_id>/update_identity", methods=["POST"])
def update_record_identity(donation_id):
    current_record = None
    for item in build_donation_flow_items():
        if item.get("donation_id") == donation_id:
            current_record = item
            break

    current_identity = load_donation_identity(donation_id, current_record or {})

    wallet_note = (request.form.get("wallet_note") or "").strip()
    display_name = (request.form.get("display_name") or "").strip() or "Arboris"
    private_note = (request.form.get("private_note") or request.form.get("internal_donor") or "").strip()
    message_note = (request.form.get("message_note") or request.form.get("public_note") or "").strip()

    # Button: use the on-chain wallet note as the public donor/display name.
    # This is intentionally manual, because wallet notes are not trusted automatically.
    if request.form.get("use_wallet_note_as_display_name") and wallet_note:
        display_name = wallet_note[:80].strip()

    # Checkbox or button: include the wallet note in future public message drafts.
    include_wallet_note = bool(request.form.get("include_wallet_note_in_message"))
    if request.form.get("use_wallet_note_in_message") and wallet_note:
        include_wallet_note = True

    include_message_note = bool(request.form.get("include_message_note_in_message"))

    # Checkbox: remember this sender wallet => display name for future donations.
    if request.form.get("save_wallet_display_mapping") and current_record:
        wallet_address = wallet_address_from_record(current_record)
        if wallet_address and display_name:
            save_wallet_display_mapping(wallet_address, display_name, private_note)

    manual_update = current_identity.get("tree_nation_manual_update") or {"needed": False, "updated": False}

    if request.form.get("mark_tree_nation_update_needed"):
        manual_update = {
            "needed": True,
            "updated": False,
            "reason": "Display name or public message changed after Tree-Nation posting.",
            "marked_at": now_iso(),
            "updated_at": None,
        }

    if request.form.get("mark_tree_nation_updated"):
        manual_update = {
            "needed": False,
            "updated": True,
            "reason": manual_update.get("reason", "Manual Tree-Nation post update completed."),
            "marked_at": manual_update.get("marked_at"),
            "updated_at": now_iso(),
        }

    identity = {
        "display_name": display_name,
        "private_note": private_note,
        "wallet_note": wallet_note,
        "message_note": message_note,
        "include_wallet_note_in_message": include_wallet_note,
        "include_message_note_in_message": include_message_note,
        "use_wallet_note_as_display_name": bool(request.form.get("use_wallet_note_as_display_name")),
        "tree_nation_manual_update": manual_update,
    }

    save_donation_identity(donation_id, identity)
    refresh_pending_decisions_for_identity(donation_id)

    # If the donation is already waiting for final planting confirmation,
    # continue directly to that page after saving donor/message settings.
    next_href = pending_decision_href_for_donation(donation_id)
    if next_href:
        return redirect(next_href)

    return redirect(f"/record/{donation_id}?saved=1")

@app.route("/suggestions")
def suggestions():
    # Show only direct planting suggestions that still need project selection.
    # Old suggestion files stay on disk as audit trail but must not appear as active work.
    suggestions = pending_project_selection_items()
    return render_template("suggestions.html", suggestions=suggestions)


@app.route("/decisions")
def decisions():
    decision_items = attach_human_labels_to_decisions(prepare_decision_items())
    return render_template("decisions.html", decisions=decision_items)


@app.route("/blocked")
def blocked():
    blocked_items = load_blocked_donations()
    return render_template("blocked.html", blocked=blocked_items)



def direct_planting_locked_for_donation(donation_id):
    """
    Safety lock:
    Once a direct planting is completed, or once one approval is already waiting,
    project selection must not silently overwrite the decision again.
    """
    if not donation_id:
        return {
            "locked": False,
            "reason": None,
            "file": None,
            "status": None
        }

    # Check decision files first
    for item in prepare_decision_items():
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        if data.get("donation_id") != donation_id:
            continue

        status = data.get("status")

        if status == "planting_completed":
            return {
                "locked": True,
                "reason": "Direct planting already completed.",
                "file": item.get("file"),
                "status": status
            }

        if data.get("planting_file"):
            return {
                "locked": True,
                "reason": "This decision already has a planting file attached.",
                "file": item.get("file"),
                "status": status
            }

        tree_nation = data.get("tree_nation", {})
        if isinstance(tree_nation, dict) and tree_nation.get("payment_id"):
            return {
                "locked": True,
                "reason": "This decision already has a Tree-Nation payment ID.",
                "file": item.get("file"),
                "status": status
            }

        if status in ["selected", "selected_pending_planting"]:
            return {
                "locked": True,
                "reason": "A planting approval is already waiting for this donation.",
                "file": item.get("file"),
                "status": status
            }

    # Check planting records too
    plantings_dir = DATA_ROOT / "plantings"
    for item in load_json_files(plantings_dir):
        data = item.get("data", {})
        if isinstance(data, dict) and data.get("donation_id") == donation_id:
            return {
                "locked": True,
                "reason": "A planting record already exists for this donation.",
                "file": item.get("file"),
                "status": "planting_record_exists"
            }

    return {
        "locked": False,
        "reason": None,
        "file": None,
        "status": None
    }


def workflow_stop_page(title, message, primary_link="/planting", primary_label="Back to Planting & CO2 Workspace", secondary_link=None, secondary_label=None):
    secondary_html = ""
    if secondary_link and secondary_label:
        secondary_html = f' | <a href="{secondary_link}">{secondary_label}</a>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <h1>🌲 The Pioneer Forest Operations Center</h1>
        <p><a href="/">Overview</a> | <a href="/planting">Planting & CO2</a> | <a href="/overview">Activity & History</a></p>
        <hr>
        <h2>{title}</h2>
        <div class="card card-warning">
            <h3>Action stopped for safety</h3>
            <p>{message}</p>
        </div>
        <p><a href="{primary_link}">{primary_label}</a>{secondary_html}</p>
    </body>
    </html>
    """


@app.route("/select_option", methods=["POST"])
def select_option():
    suggestion_file = request.form["file"]
    flat_index = int(request.form["option_index"])

    suggestion_path = DATA_ROOT / "suggestions" / suggestion_file

    with open(suggestion_path, "r", encoding="utf-8-sig") as f:
        suggestion = json.load(f)

    option_source = str(request.form.get("option_source") or "valid").strip().lower()
    if option_source == "exception":
        raw_options = suggestion.get("invalid_options") or []
    else:
        option_source = "valid"
        raw_options = (
            suggestion.get("options")
            or suggestion.get("suggestions")
            or suggestion.get("direct_planting_options")
            or []
        )

    options_flat = normalize_options(raw_options)
    if flat_index < 0 or flat_index >= len(options_flat):
        return workflow_stop_page("Selection blocked", "Invalid project option index. No approval was created.")

    selected_option = options_flat[flat_index]
    option_status = str(selected_option.get("status", "OK")).strip().upper()
    donor_choice_exception = None

    if option_status != "OK":
        exception_confirmed = request.form.get("donor_choice_exception") == "1"
        exception_reason = str(request.form.get("exception_reason") or "").strip()
        if not exception_confirmed or not exception_reason:
            return workflow_stop_page(
                "Donor-choice exception not confirmed",
                "This option is below the configured CO₂ minimum. To use it, explicitly approve the donor-requested tree/species exception and enter the donor's requested preference. No approval was created.",
                primary_link=f"/record/{suggestion.get('donation_id') or suggestion.get('donation', {}).get('donation_id') or suggestion_file.replace('suggestion_', '').replace('.json', '')}",
                primary_label="Back to Donation Record"
            )
        donor_choice_exception = {
            "approved": True,
            "approved_at": now_iso(),
            "reason": exception_reason,
            "normal_co2_rule_overridden": True,
            "option_status": selected_option.get("status"),
            "required_co2_kg": selected_option.get("required_co2_kg", selected_option.get("required_co2")),
            "selected_total_co2_kg": selected_option.get("total_co2", selected_option.get("total_co2_kg")),
            "coverage_percent": selected_option.get("coverage_percent"),
        }

    donation_id = (
        suggestion.get("donation_id")
        or suggestion.get("donation", {}).get("donation_id")
        or suggestion_file.replace("suggestion_", "").replace(".json", "")
    )

    lock = direct_planting_locked_for_donation(donation_id)

    if lock.get("locked"):
        details = (
            f"{lock.get('reason')}<br>"
            f"Donation: <b>{donation_id}</b><br>"
            f"Related file: <b>{lock.get('file')}</b><br>"
            f"Status: <b>{lock.get('status')}</b><br><br>"
            "The project selection was not changed and no new approval was created."
        )

        return workflow_stop_page(
            "Selection blocked",
            details,
            primary_link="/decisions",
            primary_label="Open Final Approval",
            secondary_link="/planting",
            secondary_label="Back to Workspace"
        )

    decision = {
        "created_at": now_iso(),
        "donation_id": donation_id,
        "donation": suggestion.get("donation", {}),
        "source_suggestion_file": suggestion_file,
        "selected_option_index": flat_index,
        "selected_option_source": option_source,
        "selected_option": selected_option,
        "status": "selected_pending_planting"
    }
    if donor_choice_exception:
        decision["donor_choice_exception"] = donor_choice_exception
    decision = enrich_decision_with_donation_identity(decision)
    decision["tree_nation_message"] = build_direct_tree_nation_message(decision)

    decisions_dir = DATA_ROOT / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    decision_file = f"decision_{suggestion_file.replace('.json', '')}_{int(time.time())}.json"
    decision_path = decisions_dir / decision_file

    with open(decision_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2, ensure_ascii=False)

    return redirect("/decisions")


@app.route("/confirm_planting/<decision_file>")
def confirm_planting(decision_file):
    decision_path = DATA_ROOT / "decisions" / decision_file

    with open(decision_path, "r", encoding="utf-8-sig") as f:
        decision = json.load(f)

    decision = enrich_decision_with_donation_identity(decision)
    # Rebuild draft from latest identity each time this page opens.
    # The final POST stores the operator-approved textarea text.
    draft_decision = dict(decision)
    draft_decision["tree_nation_message"] = ""
    tree_nation_message = build_direct_tree_nation_message(draft_decision)
    decision["tree_nation_message"] = tree_nation_message
    save_json(decision_path, decision)

    summary = selected_option_summary(decision)

    return render_template(
        "confirm_planting.html",
        decision_file=decision_file,
        decision=decision,
        summary=summary,
        tree_nation_message=tree_nation_message
    )


@app.route("/run/plant_decision", methods=["POST"])
def plant_decision():
    decision_file = request.form["decision_file"]
    confirmation = request.form.get("confirmation", "").strip()

    if confirmation != "YES":
        return "Planting blocked. You must type YES exactly."

    decision_path = DATA_ROOT / "decisions" / decision_file

    if not decision_path.exists():
        return f"Decision file not found in UI before backend call: {decision_path}"

    tree_nation_message = (request.form.get("tree_nation_message") or "").strip()
    if not tree_nation_message:
        return "Planting blocked. Tree-Nation public message is empty."
    if "#ThePioneerForest" not in tree_nation_message:
        return "Planting blocked. Tree-Nation public message must contain #ThePioneerForest."

    decision = load_json(decision_path, {}) or {}
    decision = enrich_decision_with_donation_identity(decision)
    decision["tree_nation_message"] = tree_nation_message
    save_json(decision_path, decision)

    logs_dir = DATA_ROOT / "ui-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"planting_ui_{int(time.time())}.txt"

    # Important fix:
    # plant_from_decision.py asks for a decision file path.
    # Passing only the filename caused "[ERROR] Decision file not found."
    # We now feed the FULL absolute path, then YES.
    decision_path_text = str(decision_path)

    try:
        result = subprocess.run(
            ["python", str(SCRIPTS_DIR / "plant_from_decision.py"), decision_path_text],
            cwd=str(ROOT_DIR),
            input=f"{decision_path_text}\nYES\n",
            capture_output=True,
            text=True,
            timeout=180
        )

        output = result.stdout
        if result.stderr:
            output += "\n\n--- STDERR ---\n" + result.stderr
        output += f"\n\nExit code: {result.returncode}"

    except subprocess.TimeoutExpired as e:
        output = "Planting script timed out after 180 seconds.\n"
        output += "It may be waiting for interactive input in the terminal.\n\n"
        output += str(e)

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    return render_template(
        "planting_result.html",
        decision_file=decision_file,
        output=output,
        log_file=str(log_file)
    )


@app.route("/run/process_pending/<filename>", methods=["POST"])
def process_pending(filename):
    selected_path = PENDING_DIR / filename

    if not selected_path.exists():
        # A prior click/process may already have moved this input to processed_input.
        # Do not throw a dead-end error; recover the donation id and route the user
        # to the workflow's current state.
        for item in load_json_files(PROCESSED_INPUT_DIR):
            src_name = str(item.get("file") or "")
            if src_name.endswith("_" + filename) or filename in src_name:
                data = item.get("data", {})
                donation_id = data.get("donation_id") if isinstance(data, dict) else None
                if donation_id:
                    return redirect_after_processing(donation_id)
        return redirect("/planting?pending=already_moved")

    donation = load_json(selected_path, None)

    if not donation:
        return f"Could not read pending file: {filename}"

    donation_id = donation.get("donation_id")

    if has_donation_completed(donation_id):
        archive_pending_files_for_donation(donation_id)
        return redirect("/planting")

    # Compatibility bridge:
    # older backend scripts still read data/donations/pending/donation_test_001.json.
    # We write the selected real donation there only for the duration of processing.
    if WORKING_DONATION_FILE.exists():
        try:
            WORKING_DONATION_FILE.unlink()
        except Exception:
            pass

    save_json(WORKING_DONATION_FILE, donation)

    subprocess.run(
        ["python", str(SCRIPTS_DIR / "process_donation.py")],
        cwd=str(ROOT_DIR)
    )

    # Remove the compatibility copy so it cannot appear later as a fake pending donation.
    if WORKING_DONATION_FILE.exists():
        try:
            WORKING_DONATION_FILE.unlink()
        except Exception:
            pass

    if has_donation_completed(donation_id):
        archive_pending_files_for_donation(donation_id)

    return redirect_after_processing(donation_id)

@app.route("/run/archive_pending/<filename>", methods=["POST"])
def archive_pending(filename):
    selected_path = PENDING_DIR / filename

    if not selected_path.exists():
        return redirect("/planting")

    donation = load_json(selected_path, None)

    if donation and donation.get("donation_id"):
        archive_pending_files_for_donation(donation.get("donation_id"))

    return redirect("/planting")


@app.route("/run/archive_completed_pending", methods=["POST"])
def archive_completed_pending():
    archive_completed_pending_inputs()
    return redirect("/planting")


@app.route("/run/create_pool", methods=["POST"])
def create_pool():
    subprocess.run(
        ["python", str(SCRIPTS_DIR / "create_pool_from_selection.py")],
        cwd=str(ROOT_DIR)
    )
    return redirect("/pools")



@app.route("/run/refresh_catalog", methods=["POST"])
def refresh_catalog():
    logs_dir = DATA_ROOT / "ui-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"catalog_refresh_{int(time.time())}.txt"

    result = run_catalog_refresh()

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"Script: {result.get('script')}\n")
        f.write(f"Exit code: {result.get('exit_code')}\n\n")
        f.write(result.get("output", ""))

    return render_template(
        "catalog_refresh_result.html",
        result=result,
        log_file=str(log_file),
        catalog=catalog_status()
    )



def _validated_pool_owner(availability, kind, partner_id):
    """Owner is set before planting; a shared pool has no owner."""
    if availability == "shared":
        return None, None
    if kind == "tpf":
        return "tpf", None
    if kind == "partner" and partner_id and _read_partner(partner_id):
        return "partner", partner_id
    raise ValueError("For a dedicated pool, choose TPF project or an existing partner.")


@app.route("/pool/create", methods=["GET", "POST"])
def create_pool_page():
    pool_id = pool_next_id()
    if request.method == "POST":
        allocation_basis = "trees" if request.form.get("allocation_basis") == "trees" else "co2"
        pool_name = (request.form.get("pool_name") or "").strip()
        pool_availability = "dedicated" if request.form.get("pool_availability") == "dedicated" else "shared"
        owner_kind = (request.form.get("owner_kind") or "").strip()
        owner_partner_id = (request.form.get("owner_partner_id") or "").strip()
        show_all = request.form.get("show_all") == "1"
        category_filter = (request.form.get("category_filter") or "").strip()
        try:
            target_value = int(request.form.get("target_value", 20 if allocation_basis == "trees" else 1000))
        except Exception:
            target_value = 20 if allocation_basis == "trees" else 1000
    else:
        allocation_basis = request.args.get("allocation_basis", "co2")
        allocation_basis = "trees" if allocation_basis == "trees" else "co2"
        pool_name = ""
        requested_partner = (request.args.get("partner_id") or "").strip()
        owner_partner_id = requested_partner if _read_partner(requested_partner) else ""
        pool_availability = "dedicated" if owner_partner_id else "shared"
        owner_kind = "partner" if owner_partner_id else ""
        show_all = False
        category_filter = ""
        try:
            target_value = int(request.args.get("target_value", 20 if allocation_basis == "trees" else 1000))
        except (TypeError, ValueError):
            target_value = 20 if allocation_basis == "trees" else 1000

    target_value = max(1, target_value)
    all_options = pool_catalog_options(target_value, allocation_basis, show_all=show_all)
    categories = sorted({o.get("category") for o in all_options if o.get("category")})
    options = [o for o in all_options if not category_filter or o.get("category") == category_filter]
    return render_template("create_pool.html", pool_id=pool_id, pool_name=pool_name, allocation_basis=allocation_basis, pool_availability=pool_availability,
                           owner_kind=owner_kind, owner_partner_id=owner_partner_id, partners=_all_partners(),
                           target_value=target_value, show_all=show_all, category_filter=category_filter, categories=categories, options=options, catalog=catalog_status())


@app.route("/pool/confirm", methods=["POST"])
def confirm_pool_page():
    pool_id = request.form.get("pool_id") or pool_next_id()
    pool_name = (request.form.get("pool_name") or "").strip()
    allocation_basis = "trees" if request.form.get("allocation_basis") == "trees" else "co2"
    pool_availability = "dedicated" if request.form.get("pool_availability") == "dedicated" else "shared"
    try:
        owner_kind, owner_partner_id = _validated_pool_owner(pool_availability, request.form.get("owner_kind"), request.form.get("owner_partner_id"))
    except ValueError as exc:
        return render_template("pool_result.html", ok=False, title="Choose pool owner", message=str(exc) + " No Tree-Nation API call was made.", result=None), 400
    if pool_name and pool_name_exists(pool_name):
        return render_template("pool_result.html", ok=False, title="Pool Name Already Exists",
                               message=f'A pool named “{pool_name}” already exists. Please choose a different name. No Tree-Nation API call was made.', result=None)
    show_all = request.form.get("show_all") == "1"
    try:
        target_value = max(1, int(request.form.get("target_value", 20 if allocation_basis == "trees" else 1000)))
        option_index = int(request.form.get("option_index", -1))
    except Exception:
        target_value = 20 if allocation_basis == "trees" else 1000
        option_index = -1

    category_filter = (request.form.get("category_filter") or "").strip()
    options = pool_catalog_options(target_value, allocation_basis, show_all=show_all)
    if category_filter:
        options = [o for o in options if o.get("category") == category_filter]
    if option_index < 0 or option_index >= len(options):
        return render_template("pool_result.html", ok=False, title="Pool option not found",
                               message="The selected pool option could not be found. Go back and try again.", result=None)

    selected = options[option_index]
    tree_nation_message = default_pool_message(pool_id, pool_name, allocation_basis, target_value, selected, pool_availability)
    return render_template("confirm_pool.html", pool_id=pool_id, pool_name=pool_name, allocation_basis=allocation_basis, pool_availability=pool_availability,
                           owner_kind=owner_kind, owner_partner_id=owner_partner_id,
                           owner_label=("TPF project" if owner_kind == "tpf" else _read_partner(owner_partner_id)["name"] if owner_kind == "partner" else "Shared"),
                           target_value=target_value, show_all=show_all, category_filter=category_filter, selected=selected,
                           option_index=option_index, tree_nation_message=tree_nation_message)


@app.route("/pool/create_final", methods=["POST"])
def create_pool_final():
    pool_id = request.form.get("pool_id") or pool_next_id()
    pool_name = (request.form.get("pool_name") or "").strip()
    allocation_basis = "trees" if request.form.get("allocation_basis") == "trees" else "co2"
    pool_availability = "dedicated" if request.form.get("pool_availability") == "dedicated" else "shared"
    try:
        owner_kind, owner_partner_id = _validated_pool_owner(pool_availability, request.form.get("owner_kind"), request.form.get("owner_partner_id"))
    except ValueError as exc:
        return render_template("pool_result.html", ok=False, title="Pool creation blocked", message=str(exc) + " No Tree-Nation API call was made.", result=None), 400
    if pool_name and pool_name_exists(pool_name):
        return render_template("pool_result.html", ok=False, title="Pool Name Already Exists",
                               message=f'A pool named “{pool_name}” already exists. Please choose a different name. No Tree-Nation API call was made.', result=None)
    show_all = request.form.get("show_all") == "1"
    try:
        target_value = max(1, int(request.form.get("target_value", 20 if allocation_basis == "trees" else 1000)))
        option_index = int(request.form.get("option_index", -1))
    except Exception:
        target_value = 20 if allocation_basis == "trees" else 1000
        option_index = -1

    confirm = request.form.get("confirm", "").strip()
    tree_nation_message = (request.form.get("tree_nation_message") or "").strip()
    exception_confirm = request.form.get("exception_confirm") == "1"
    exception_reason = (request.form.get("exception_reason") or "").strip()

    if confirm != "YES":
        return render_template("pool_result.html", ok=False, title="Pool creation cancelled",
                               message="Confirmation text was not YES. No Tree-Nation API call was made.", result=None)

    category_filter = (request.form.get("category_filter") or "").strip()
    options = pool_catalog_options(target_value, allocation_basis, show_all=show_all)
    if category_filter:
        options = [o for o in options if o.get("category") == category_filter]
    if option_index < 0 or option_index >= len(options):
        return render_template("pool_result.html", ok=False, title="Pool option not found",
                               message="The selected pool option could not be found. No Tree-Nation API call was made.", result=None)
    selected = options[option_index]

    if selected.get("option_status") == "red" and (not exception_confirm or not exception_reason):
        return render_template("pool_result.html", ok=False, title="Pool Creation Blocked",
                               message="This option is below the entered target. Confirm the manual exception and provide a reason. No Tree-Nation API call was made.", result=None)

    if not tree_nation_message:
        tree_nation_message = default_pool_message(pool_id, pool_name, allocation_basis, target_value, selected, pool_availability)
    if "#ThePioneerForest" not in tree_nation_message:
        return render_template("pool_result.html", ok=False, title="Pool Creation Blocked",
                               message="The Tree-Nation message must include #ThePioneerForest. No Tree-Nation API call was made.", result=None)

    result = create_pool_from_browser(pool_id, pool_name, allocation_basis, pool_availability, target_value, selected, tree_nation_message,
                                      exception_reason if selected.get("option_status") == "red" else None, owner_kind, owner_partner_id)
    label = f"{'Dedicated' if pool_availability == 'dedicated' else 'Shared'} {'Tree' if allocation_basis == 'trees' else 'CO2'} Pool Created"
    return render_template("pool_result.html", ok=result.get("ok"), title=label if result.get("ok") else "Pool Creation Failed",
                           message=result.get("message"), result=result)


# ---------------------------------------------------------------------------
# Wallet Watcher — Mainnet read-only observer
# ---------------------------------------------------------------------------

def wallet_watcher_dir():
    # Wallet Watcher is now explicitly separated as MAINNET data.
    # Old location was data/wallet-watcher. Active location is data/mainnet/wallet-watcher.
    path = DATA_ROOT / "wallet-watcher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def wallet_sources_file():
    return wallet_watcher_dir() / "sources.json"


def wallet_transactions_file():
    return wallet_watcher_dir() / "transactions.json"


def wallet_blockchain_archive_file():
    # Append-only local blockchain archive. Stores incoming AND outgoing wallet movements.
    # This is the raw audit layer below the interpreted master ledger.
    return wallet_watcher_dir() / "wallet_blockchain_archive.json"


def wallet_master_file():
    return wallet_watcher_dir() / "transactions_master.json"


def default_wallet_sources():
    return [
        {
            "source_id": "tpf_public_mainnet",
            "label": "TPF Public Wallet",
            "wallet_address": "GDJQWS634MNY2XQ6FKOM6Z2PP5RQWEWLBNQICV43WI4IVWT3RC7VHD3M",
            "network": "mainnet",
            "role": "public_donations",
            "mode": "read_only",
            "enabled": True,
            "notes": "Publicly announced TPF donation wallet. Mainnet observer only. No import, no donation creation, no planting."
        }
    ]


def load_wallet_sources():
    sources = load_json(wallet_sources_file(), None)
    if not isinstance(sources, list) or not sources:
        sources = default_wallet_sources()
        save_json(wallet_sources_file(), sources)
    return sources


def strip_display_emojis(value):
    text = str(value or "").strip()
    if not text:
        return ""

    cleaned = []
    for ch in text:
        code = ord(ch)
        if 0x1F000 <= code <= 0x1FAFF:
            continue
        if 0x2600 <= code <= 0x27BF:
            continue
        if 0xFE00 <= code <= 0xFE0F:
            continue
        cleaned.append(ch)

    return " ".join("".join(cleaned).split())


def load_wallet_master():
    master = load_json(wallet_master_file(), {}) or {}
    return master if isinstance(master, dict) else {}


def wallet_master_by_tx_hash():
    master = load_wallet_master()
    lookup = {}

    for record in master.get("transactions", []) or []:
        if not isinstance(record, dict):
            continue
        tx_hash = (record.get("tx_hash") or "").lower().strip()
        if tx_hash:
            lookup[tx_hash] = record

    return lookup


def donor_names_from_master_record(record):
    summary = record.get("history_summary", {}) if isinstance(record, dict) else {}
    names = summary.get("donor_names") if isinstance(summary, dict) else []

    if not isinstance(names, list):
        names = []

    cleaned = []
    for name in names:
        clean = strip_display_emojis(name)
        if clean and clean not in cleaned:
            cleaned.append(clean)

    return cleaned


def wallet_master_ui_summary():
    master = load_wallet_master()
    records = master.get("transactions", []) if isinstance(master, dict) else []

    if not isinstance(records, list):
        records = []

    matched = sum(1 for r in records if isinstance(r, dict) and r.get("history_match_status") == "matched_history")
    unmatched = sum(1 for r in records if isinstance(r, dict) and r.get("history_match_status") == "unmatched_blockchain")
    ignored = sum(1 for r in records if isinstance(r, dict) and r.get("history_match_status") in ["ignored_test_payment", "ignored_manual"])

    return {
        "available": bool(master),
        "created_at": master.get("created_at", "—") if isinstance(master, dict) else "—",
        "mode": master.get("mode", "—") if isinstance(master, dict) else "—",
        "total": len(records),
        "matched": matched,
        "unmatched": unmatched,
        "ignored": ignored
    }


def wallet_transaction_url_from_payment(payment):
    """Return the transaction-detail URL from a Pi Horizon payment operation."""
    if not isinstance(payment, dict):
        return ""

    link_url = payment.get("_links", {}).get("transaction", {}).get("href")
    if link_url:
        return link_url

    tx_hash = payment.get("transaction_hash") or payment.get("tx_hash")
    if tx_hash:
        return f"https://api.mainnet.minepi.com/transactions/{tx_hash}"

    return ""


def fetch_wallet_transaction_detail(payment):
    """Fetch full transaction details for one wallet payment.

    The user-facing Pi Wallet note is not always stored as an on-chain memo,
    but checking the transaction detail gives us an honest verification state:
    checked / memo found / no memo / fetch error.
    """
    tx_url = wallet_transaction_url_from_payment(payment)
    if not tx_url:
        return None, None, "No transaction URL found."

    try:
        response = requests.get(tx_url, timeout=20)
        response.raise_for_status()
        return response.json(), tx_url, None
    except Exception as exc:
        return None, tx_url, str(exc)


def extract_blockchain_memo(transaction_json):
    """Extract memo data from a full transaction JSON object."""
    if not isinstance(transaction_json, dict):
        return {
            "memo_type": None,
            "memo": "",
            "memo_status": "transaction_details_missing",
            "memo_found": False,
        }

    memo_type = transaction_json.get("memo_type") or "none"
    memo = transaction_json.get("memo")
    memo_text = str(memo or "").strip()

    if str(memo_type).lower() != "none":
        return {
            "memo_type": memo_type,
            "memo": memo_text,
            "memo_status": "memo_found" if memo_text else "memo_type_without_memo_text",
            "memo_found": bool(memo_text),
        }

    return {
        "memo_type": memo_type,
        "memo": "",
        "memo_status": "no_memo",
        "memo_found": False,
    }


def normalize_wallet_payment(source, payment, transaction_raw=None, transaction_url=None, transaction_fetch_error=None):
    wallet = (source.get("wallet_address") or "").strip()
    tx_hash = payment.get("transaction_hash") or payment.get("tx_hash") or ""
    operation_id = payment.get("id") or payment.get("operation_id") or payment.get("paging_token") or ""
    from_address = payment.get("from") or payment.get("from_address") or ""
    to_address = payment.get("to") or payment.get("to_address") or ""
    amount_raw = payment.get("amount") or payment.get("amount_pi") or 0

    try:
        amount_pi = float(amount_raw)
    except Exception:
        amount_pi = amount_raw

    memo_info = extract_blockchain_memo(transaction_raw)
    blockchain_checked = transaction_raw is not None or bool(transaction_fetch_error)
    blockchain_memo = memo_info.get("memo") or ""

    if blockchain_checked and transaction_fetch_error:
        verification_label = "Transaction check failed"
        verification_class = "unmatched-label"
    elif blockchain_checked:
        verification_label = "Transaction checked"
        verification_class = "matched-label"
    else:
        verification_label = "Transaction not checked"
        verification_class = "wallet-small-muted"

    return {
        "source_id": source.get("source_id"),
        "source_label": source.get("label", "Wallet"),
        "network": source.get("network", "mainnet"),
        "wallet_address": wallet,
        "direction": "incoming" if to_address == wallet else ("outgoing" if from_address == wallet else "other"),
        "tx_hash": tx_hash,
        "operation_id": operation_id,
        "from_address": from_address,
        "to_address": to_address,
        "amount_pi": amount_pi,
        "created_at": payment.get("created_at", "—"),
        "created_at_chain": payment.get("created_at", "—"),
        "asset_type": payment.get("asset_type", "native"),
        "memo_raw": blockchain_memo,
        "memo_type": memo_info.get("memo_type"),
        "memo_status": memo_info.get("memo_status"),
        "blockchain_checked": blockchain_checked,
        "blockchain_verified": bool(blockchain_checked and not transaction_fetch_error),
        "blockchain_memo": blockchain_memo,
        "blockchain_memo_found": bool(blockchain_memo),
        "blockchain_memo_type": memo_info.get("memo_type"),
        "blockchain_memo_status": memo_info.get("memo_status"),
        "transaction_url": transaction_url or wallet_transaction_url_from_payment(payment),
        "transaction_fetch_error": transaction_fetch_error,
        "verification_label": verification_label,
        "verification_class": verification_class,
        "status_label": "Mainnet payment",
        "raw_json": payment,
        "transaction_raw": transaction_raw,
    }


def wallet_tx_unique_key(tx):
    # Prefer operation_id because multiple operations can share a transaction hash.
    # Fall back to tx_hash if operation_id is missing.
    return (tx.get("operation_id") or tx.get("tx_hash") or "").lower().strip()


def load_wallet_blockchain_archive():
    archive = load_json(wallet_blockchain_archive_file(), {}) or {}
    if not isinstance(archive, dict):
        archive = {}

    transactions = archive.get("transactions", [])
    if not isinstance(transactions, list):
        transactions = []

    archive.setdefault("schema", "tpf_wallet_blockchain_archive_v1")
    archive.setdefault("created_at", now_iso())
    archive["transactions"] = transactions
    return archive


def wallet_blockchain_archive_summary():
    archive = load_wallet_blockchain_archive()
    records = archive.get("transactions", [])

    incoming = sum(1 for tx in records if isinstance(tx, dict) and tx.get("direction") == "incoming")
    outgoing = sum(1 for tx in records if isinstance(tx, dict) and tx.get("direction") == "outgoing")
    other = sum(1 for tx in records if isinstance(tx, dict) and tx.get("direction") not in ["incoming", "outgoing"])

    return {
        "available": bool(records),
        "total": len(records),
        "incoming": incoming,
        "outgoing": outgoing,
        "other": other,
        "created_at": archive.get("created_at", "—"),
        "updated_at": archive.get("updated_at", "—"),
        "last_fetch_at": archive.get("last_fetch_at", "—"),
        "last_added": archive.get("last_added", 0),
        "file": str(wallet_blockchain_archive_file())
    }


def wallet_backup_dir():
    path = wallet_watcher_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_wallet_backup():
    """
    Manual safety backup for Wallet Watcher core files.
    Copies files only; does not modify ledger/archive content.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S_UTC")
    target_dir = wallet_backup_dir() / timestamp
    target_dir.mkdir(parents=True, exist_ok=False)

    files_to_backup = [
        wallet_blockchain_archive_file(),
        wallet_master_file(),
        wallet_transactions_file(),
        wallet_sources_file(),
    ]

    copied = []
    missing = []

    for src in files_to_backup:
        if src.exists():
            dst = target_dir / src.name
            shutil.copy2(src, dst)
            copied.append(src.name)
        else:
            missing.append(src.name)

    manifest = {
        "schema": "tpf_wallet_backup_manifest_v1",
        "created_at": now_iso(),
        "backup_dir": str(target_dir),
        "copied_files": copied,
        "missing_files": missing,
        "note": "Manual Wallet Watcher backup. Restore by copying files back into data/mainnet/wallet-watcher if needed."
    }
    save_json(target_dir / "backup_manifest.json", manifest)

    return manifest


def append_wallet_blockchain_archive(fetched_transactions):
    archive = load_wallet_blockchain_archive()
    existing = archive.get("transactions", [])

    by_key = {}
    for tx in existing:
        if not isinstance(tx, dict):
            continue
        key = wallet_tx_unique_key(tx)
        if key:
            by_key[key] = tx

    added = 0
    for tx in fetched_transactions:
        if not isinstance(tx, dict):
            continue
        key = wallet_tx_unique_key(tx)
        if not key:
            continue

        if key not in by_key:
            tx_copy = dict(tx)
            tx_copy.setdefault("archived_at", now_iso())
            by_key[key] = tx_copy
            added += 1

    transactions = list(by_key.values())
    transactions.sort(key=lambda item: item.get("created_at") or item.get("created_at_chain") or "", reverse=True)

    archive["transactions"] = transactions
    archive["updated_at"] = now_iso()
    archive["last_fetch_at"] = now_iso()
    archive["last_added"] = added

    save_json(wallet_blockchain_archive_file(), archive)
    return wallet_blockchain_archive_summary()



def wallet_watcher_backfill_source(source, limit=200, max_pages=200):
    """
    Full-history backfill for one wallet source.
    Walks Pi Mainnet payment pages and returns incoming + outgoing + other payments.
    This only feeds the raw blockchain archive; it does not create donations or change the master ledger.
    """
    if not source.get("enabled", True):
        return [], f"Skipped disabled source: {source.get('label')}", 0

    if source.get("network") != "mainnet":
        return [], f"Skipped non-mainnet source: {source.get('label')}", 0

    wallet = source.get("wallet_address")
    if not wallet:
        return [], f"Missing wallet address for source: {source.get('label')}", 0

    base = "https://api.mainnet.minepi.com"
    url = f"{base}/accounts/{wallet}/payments?cursor=&limit={limit}&order=desc"

    all_transactions = []
    seen = set()
    pages = 0

    while url and pages < max_pages:
        pages += 1
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        payload = response.json()
        records = payload.get("_embedded", {}).get("records", [])

        if not records:
            break

        for payment in records:
            tx_json, tx_url, tx_error = fetch_wallet_transaction_detail(payment)
            normalized = normalize_wallet_payment(source, payment, tx_json, tx_url, tx_error)
            key = wallet_tx_unique_key(normalized)
            if not key or key in seen:
                continue
            seen.add(key)
            all_transactions.append(normalized)

        next_url = payload.get("_links", {}).get("next", {}).get("href")
        if not next_url or next_url == url:
            break

        # Horizon-style APIs can theoretically keep returning a next link even at the end.
        # The empty-record check above stops the loop safely.
        url = next_url

    warning = None
    if pages >= max_pages:
        warning = f"Backfill stopped at safety limit: {max_pages} pages for {source.get('label')}"

    return all_transactions, warning, pages


def wallet_watcher_backfill_all():
    """
    Full Wallet Archive backfill for all enabled sources.
    Safe behavior:
    - fetches incoming + outgoing + other payment operations
    - appends only new operations to wallet_blockchain_archive.json
    - does not modify transactions_master.json
    - does not create donations
    - does not call Tree-Nation
    """
    sources = load_wallet_sources()
    all_transactions = []
    errors = []
    warnings = []
    total_pages = 0

    for source in sources:
        try:
            txs, warning, pages = wallet_watcher_backfill_source(source)
            total_pages += pages
            all_transactions.extend(txs)
            if warning:
                warnings.append(warning)
        except Exception as exc:
            errors.append(f"{source.get('label', 'Wallet')}: {exc}")

    seen = set()
    deduped = []
    for tx in all_transactions:
        key = wallet_tx_unique_key(tx)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(tx)

    deduped.sort(key=lambda item: item.get("created_at") or item.get("created_at_chain") or "", reverse=True)

    before = wallet_blockchain_archive_summary().get("total", 0)
    archive_summary = append_wallet_blockchain_archive(deduped)
    after = archive_summary.get("total", 0)

    # Save a small report so the operator can inspect what happened later.
    report = {
        "schema": "tpf_wallet_backfill_report_v1",
        "created_at": now_iso(),
        "sources_checked": len([s for s in sources if isinstance(s, dict) and s.get("enabled", True)]),
        "pages_checked": total_pages,
        "fetched_operations": len(deduped),
        "archive_total_before": before,
        "archive_total_after": after,
        "archive_added": after - before,
        "warnings": warnings,
        "errors": errors,
    }
    reports_dir = wallet_watcher_dir() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    save_json(reports_dir / f"wallet_backfill_{int(time.time())}.json", report)

    return report

def wallet_watcher_fetch_source(source, limit=10):
    if not source.get("enabled", True):
        return [], None

    if source.get("network") != "mainnet":
        return [], f"Skipped non-mainnet source: {source.get('label')}"

    wallet = source.get("wallet_address")
    if not wallet:
        return [], f"Missing wallet address for source: {source.get('label')}"

    base = "https://api.mainnet.minepi.com"
    url = f"{base}/accounts/{wallet}/payments?cursor=&limit={limit}&order=desc"

    response = requests.get(url, timeout=20)
    response.raise_for_status()

    payload = response.json()
    records = payload.get("_embedded", {}).get("records", [])

    transactions = []
    for payment in records:
        tx_json, tx_url, tx_error = fetch_wallet_transaction_detail(payment)
        normalized = normalize_wallet_payment(source, payment, tx_json, tx_url, tx_error)
        transactions.append(normalized)

    return transactions, None


def wallet_watcher_fetch_all(limit=10):
    sources = load_wallet_sources()
    all_transactions = []
    errors = []

    for source in sources:
        try:
            transactions, warning = wallet_watcher_fetch_source(source, limit=limit)
            if warning:
                errors.append(warning)
            all_transactions.extend(transactions)
        except Exception as exc:
            errors.append(f"{source.get('label', 'Wallet')}: {exc}")

    seen = set()
    deduped_all = []
    for tx in all_transactions:
        key = wallet_tx_unique_key(tx)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_all.append(tx)

    deduped_all.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    # Permanent raw audit archive: incoming + outgoing + other.
    append_wallet_blockchain_archive(deduped_all)

    # UI recent cache remains incoming-only for the donation-facing Wallet Watcher page.
    recent_incoming = [tx for tx in deduped_all if tx.get("direction") == "incoming"]

    save_json(wallet_transactions_file(), {
        "fetched_at": now_iso(),
        "source_count": len([s for s in sources if isinstance(s, dict) and s.get("enabled", True)]),
        "transactions": recent_incoming,
        "raw_fetched_count": len(deduped_all),
        "incoming_fetched_count": len(recent_incoming),
        "errors": errors
    })

    return sources, recent_incoming, errors


def enrich_wallet_transactions_with_master(transactions):
    lookup = wallet_master_by_tx_hash()
    enriched = []

    for tx in transactions:
        tx_copy = dict(tx)
        tx_hash = (tx_copy.get("tx_hash") or "").lower().strip()
        master = lookup.get(tx_hash)

        tx_copy["master_found"] = bool(master)
        tx_copy["master_match_status"] = master.get("history_match_status") if master else "not_in_master"
        tx_copy["donor_names_clean"] = donor_names_from_master_record(master or {})
        tx_copy["history_summary"] = master.get("history_summary", {}) if master else {}
        tx_copy["history_annotations"] = master.get("history_annotations", []) if master else []
        tx_copy["history_note"] = ""
        if master and isinstance(master.get("history_annotations"), list):
            notes = []
            for item in master.get("history_annotations", []):
                note = str((item or {}).get("note_manual") or "").strip()
                if note and note not in notes:
                    notes.append(note)
            tx_copy["history_note"] = " | ".join(notes)

        if tx_copy.get("master_match_status") == "matched_history":
            tx_copy["history_status_label"] = "Already processed / archived"
            tx_copy["history_status_class"] = "matched-label"
        elif tx_copy.get("master_match_status") in ["ignored_test_payment", "ignored_manual"]:
            tx_copy["history_status_label"] = "Ignored / not a donation"
            tx_copy["history_status_class"] = "wallet-small-muted"
        else:
            tx_copy["history_status_label"] = "New blockchain payment"
            tx_copy["history_status_class"] = "unmatched-label"

        enriched.append(tx_copy)

    return enriched


def wallet_master_unmatched_transactions():
    master = load_wallet_master()
    records = master.get("transactions", []) if isinstance(master, dict) else []

    if not isinstance(records, list):
        return []

    unmatched = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("history_match_status") != "unmatched_blockchain":
            continue

        record_copy = dict(record)
        record_copy["donor_names_clean"] = donor_names_from_master_record(record)
        unmatched.append(record_copy)

    unmatched.sort(key=lambda item: item.get("created_at_chain") or "", reverse=True)
    return unmatched


def wallet_master_all_transactions():
    master = load_wallet_master()
    records = master.get("transactions", []) if isinstance(master, dict) else []

    if not isinstance(records, list):
        return []

    all_records = []

    for record in records:
        if not isinstance(record, dict):
            continue

        record_copy = dict(record)
        record_copy["donor_names_clean"] = donor_names_from_master_record(record)

        status = record_copy.get("history_match_status")
        if status == "matched_history":
            record_copy["human_status"] = "Already processed / archived"
            record_copy["human_status_class"] = "matched-label"
        elif status == "ignored_test_payment":
            record_copy["human_status"] = "Ignored test payment"
            record_copy["human_status_class"] = "wallet-small-muted"
        elif status == "ignored_manual":
            record_copy["human_status"] = "Ignored manually"
            record_copy["human_status_class"] = "wallet-small-muted"
        elif status == "unmatched_blockchain":
            record_copy["human_status"] = "New blockchain payment"
            record_copy["human_status_class"] = "unmatched-label"
        else:
            record_copy["human_status"] = status or "Unknown"
            record_copy["human_status_class"] = "wallet-small-muted"

        all_records.append(record_copy)

    all_records.sort(key=lambda item: item.get("created_at_chain") or "", reverse=True)
    return all_records



def donation_files_with_tx_hash():
    """Return known TX hashes already represented in donation workflow files.

    This protects Wallet Watcher auto-import from creating duplicate pending donations
    when the page is refreshed multiple times.
    """
    known = {}

    folders = [
        DATA_ROOT / "donations" / "pending",
        DATA_ROOT / "donations" / "processed",
        DATA_ROOT / "donations" / "processed_input",
        DATA_ROOT / "suggestions",
        DATA_ROOT / "decisions",
        DATA_ROOT / "plantings",
        DATA_ROOT / "co2-pool" / "allocations",
    ]

    def remember(tx_hash, file_name, folder_label):
        tx_hash_clean = (tx_hash or "").lower().strip()
        if not tx_hash_clean:
            return
        known.setdefault(tx_hash_clean, {
            "file": file_name,
            "folder": folder_label
        })

    for folder in folders:
        for item in load_json_files(folder):
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue

            donation = data.get("donation", {}) if isinstance(data.get("donation", {}), dict) else {}

            remember(data.get("tx_hash"), item.get("file"), folder.name)
            remember(data.get("transaction_hash"), item.get("file"), folder.name)
            remember(donation.get("tx_hash"), item.get("file"), folder.name)
            remember(donation.get("transaction_hash"), item.get("file"), folder.name)

    return known


def wallet_pending_donation_filename(tx_hash):
    tx_hash_clean = re.sub(r"[^a-zA-Z0-9]", "", tx_hash or "").lower()
    short = tx_hash_clean[:16] if tx_hash_clean else str(int(time.time()))
    return f"donation_wallet_{short}.json"


def create_pending_donation_from_wallet_tx(tx, purpose_reason="", classification="tree_offset"):
    """Create one pending donation JSON from an incoming wallet transaction.

    This is the bridge between Wallet Watcher and the Planting & CO₂ workflow.
    It does not process the donation, allocate CO₂, plant trees, or call Tree-Nation.
    """
    tx_hash = (tx.get("tx_hash") or "").strip()
    if not tx_hash:
        return {"ok": False, "message": "Missing transaction hash."}

    try:
        amount_pi = float(tx.get("amount_pi", 0) or 0)
    except Exception:
        return {"ok": False, "message": "Invalid Pi amount."}

    if amount_pi <= 0:
        return {"ok": False, "message": "Amount is not positive."}

    file_name = wallet_pending_donation_filename(tx_hash)
    file_path = PENDING_DIR / file_name

    if file_path.exists():
        return {"ok": True, "created": False, "file": file_name, "message": "Pending donation already exists."}

    # Do not auto-trust blockchain memo as a public donor name.
    # Operator can later use the wallet note as display name from the record page.
    mapped_name = mapped_display_name_for_record(tx)
    donor = mapped_name or "Arboris"

    tx_short = re.sub(r"[^a-zA-Z0-9]", "", tx_hash).lower()[:12]
    donation_id = f"wallet_{tx_short}" if tx_short else f"wallet_{int(time.time())}"

    donation = {
        "schema": "tpf_pending_donation_from_wallet_v1",
        "donation_id": donation_id,
        "donor": donor,
        "amount_pi": amount_pi,
        "tx_hash": tx_hash,
        "source": "wallet_watcher_mainnet",
        "status": "pending",
        "created_at": now_iso(),
        "wallet_source_id": tx.get("source_id"),
        "wallet_source_label": tx.get("source_label"),
        "network": tx.get("network", "mainnet"),
        "from_address": tx.get("from_address"),
        "to_address": tx.get("to_address"),
        "operation_id": tx.get("operation_id"),
        "chain_created_at": tx.get("created_at_chain") or tx.get("created_at"),
        "memo_raw": tx.get("blockchain_memo") or tx.get("memo_raw", ""),
        "memo_type": tx.get("blockchain_memo_type") or tx.get("memo_type"),
        "memo_status": tx.get("blockchain_memo_status") or tx.get("memo_status"),
        "blockchain_checked": tx.get("blockchain_checked", False),
        "blockchain_verified": tx.get("blockchain_verified", False),
        "transaction_url": tx.get("transaction_url"),
        "transaction_fetch_error": tx.get("transaction_fetch_error"),
        "purpose_classification": classification,
        "purpose_reason": str(purpose_reason or "").strip(),
        "review_note": "Confirmed in Wallet Watcher as Tree / Offset Donation. Processing continues through the Planting & CO₂ workflow.",
        "raw_wallet_tx": tx.get("raw_json", tx),
        "raw_transaction": tx.get("transaction_raw"),
    }

    save_json(file_path, donation)

    return {
        "ok": True,
        "created": True,
        "file": file_name,
        "donation_id": donation_id,
        "message": "Pending donation created."
    }




# ---------------------------------------------------------------------------
# TPF Funds — shared incoming/outgoing classification base
# ---------------------------------------------------------------------------

DEFAULT_TPF_FUNDS = [
    {
        "id": "partner_pool_payments", "name": "Partner Pool Payments",
        "fund_type": "base", "workflow": "record_only", "status": "active",
        "description": "Verified partner offer payments. Match to a selected order; planting follows that offer.",
        "sort_order": 15,
    },
    {
        "id": "reforestation_co2",
        "name": "Reforestation / CO₂",
        "fund_type": "base",
        "workflow": "planting",
        "description": "Funds assigned to tree planting, reforestation and CO₂ offset activity.",
        "status": "active",
        "sort_order": 10,
    },
    {
        "id": "general_tpf_support",
        "name": "General TPF Support",
        "fund_type": "base",
        "workflow": "record_only",
        "description": "Flexible support for The Pioneer Forest that is not restricted to a specific cause.",
        "status": "active",
        "sort_order": 20,
    },
    {
        "id": "hardware_infrastructure",
        "name": "Hardware & Infrastructure",
        "fund_type": "base",
        "workflow": "record_only",
        "description": "Hardware, hosting, equipment and technical infrastructure for TPF.",
        "status": "active",
        "sort_order": 30,
    },
    {
        "id": "creative_media",
        "name": "Creative / Media",
        "fund_type": "base",
        "workflow": "record_only",
        "description": "Art, design, music, video and other creative work supporting TPF.",
        "status": "active",
        "sort_order": 40,
    },
    {
        "id": "reimbursement_fiat_co2",
        "name": "Reimbursement — Fiat CO₂ Funding",
        "fund_type": "base",
        "workflow": "record_only",
        "description": "Pi assigned to reimburse verified tree / CO₂ purchases that were already paid from the real-money (€) side.",
        "status": "active",
        "sort_order": 50,
    },
]


def funds_dir():
    path = DATA_ROOT / "funds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def funds_file():
    return funds_dir() / "funds.json"


def fund_ledger_file():
    return funds_dir() / "fund_ledger.json"


def clean_fund_id(value):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip().lower()).strip("_")
    return value[:80]


def ensure_default_funds():
    data = load_json(funds_file(), None)
    if not isinstance(data, dict):
        data = {"schema": "tpf_funds_v1", "funds": []}

    funds = data.get("funds")
    if not isinstance(funds, list):
        funds = []

    existing = {str(f.get("id") or "") for f in funds if isinstance(f, dict)}
    changed = False
    for default in DEFAULT_TPF_FUNDS:
        if default["id"] not in existing:
            funds.append(dict(default))
            changed = True

    data["schema"] = "tpf_funds_v1"
    data["funds"] = funds
    data["updated_at"] = now_iso()
    if changed or not funds_file().exists():
        save_json(funds_file(), data)
    return data


def load_funds(active_only=False):
    data = ensure_default_funds()
    funds = [f for f in data.get("funds", []) if isinstance(f, dict)]
    if active_only:
        funds = [f for f in funds if str(f.get("status", "active")).lower() == "active"]
    return sorted(funds, key=lambda f: (int(f.get("sort_order", 9999)), str(f.get("name") or "").lower()))


def get_fund(fund_id):
    fid = str(fund_id or "").strip()
    for fund in load_funds(False):
        if str(fund.get("id") or "") == fid:
            return fund
    return None


def save_funds(funds):
    save_json(funds_file(), {
        "schema": "tpf_funds_v1",
        "updated_at": now_iso(),
        "funds": funds,
    })


def load_fund_ledger():
    data = load_json(fund_ledger_file(), None)
    if not isinstance(data, dict):
        data = {"schema": "tpf_fund_ledger_v1", "entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    return data


def add_fund_ledger_entry(entry):
    data = load_fund_ledger()
    entries = data["entries"]

    tx_hash = str(entry.get("tx_hash") or "").strip().lower()
    transfer_id = str(entry.get("internal_transfer_id") or "").strip().lower()
    direction = str(entry.get("direction") or "").strip().lower()
    fund_id = str(entry.get("fund_id") or "").strip()

    # Idempotency:
    # - blockchain movements use tx_hash + direction + fund
    # - accounting-only internal transfers use internal_transfer_id + direction + fund
    for existing in entries:
        existing_direction = str(existing.get("direction") or "").strip().lower()
        existing_fund_id = str(existing.get("fund_id") or "").strip()

        if tx_hash:
            if (
                str(existing.get("tx_hash") or "").strip().lower() == tx_hash
                and existing_direction == direction
                and existing_fund_id == fund_id
            ):
                return existing

        if transfer_id:
            if (
                str(existing.get("internal_transfer_id") or "").strip().lower() == transfer_id
                and existing_direction == direction
                and existing_fund_id == fund_id
            ):
                return existing

    payload = dict(entry)
    payload["id"] = payload.get("id") or f"fund_{len(entries)+1:06d}"
    payload["created_at"] = payload.get("created_at") or now_iso()
    entries.append(payload)
    data["updated_at"] = now_iso()
    save_json(fund_ledger_file(), data)
    return payload



def fetch_wallet_native_balance(wallet_address):
    """Read the current native Pi balance for one Mainnet wallet.

    Read-only Horizon-style account lookup. Returns None on failure so the
    accounting UI never invents a balance.
    """
    wallet = str(wallet_address or "").strip()
    if not wallet:
        return None, "Missing wallet address"

    try:
        response = requests.get(
            f"https://api.mainnet.minepi.com/accounts/{wallet}",
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

        for balance in payload.get("balances", []):
            if not isinstance(balance, dict):
                continue
            if balance.get("asset_type") == "native":
                try:
                    return float(balance.get("balance")), None
                except Exception:
                    return None, "Native balance was not numeric"

        return None, "Native Pi balance not found"
    except Exception as exc:
        return None, str(exc)


def wallet_fund_reconciliation_summary():
    """Compare the public donation wallet's real balance with fund accounting.

    For now the Funds ledger belongs to the TPF Public Wallet. If additional
    wallet sources are added later, they stay separate rather than being silently
    merged into this balance.
    """
    sources = load_wallet_sources()

    public_source = next(
        (
            source for source in sources
            if isinstance(source, dict)
            and source.get("enabled", True)
            and source.get("network") == "mainnet"
            and source.get("role") == "public_donations"
        ),
        None,
    )

    wallet_balance = None
    balance_error = None
    wallet_label = "TPF Public Wallet"
    wallet_address = ""

    if public_source:
        wallet_label = public_source.get("label") or wallet_label
        wallet_address = public_source.get("wallet_address") or ""
        wallet_balance, balance_error = fetch_wallet_native_balance(wallet_address)
    else:
        balance_error = "No enabled Mainnet public donation wallet configured."

    funds = fund_balance_summary()
    allocated = round(sum(float(f.get("balance_pi") or 0) for f in funds), 7)

    unallocated = None
    reconciled = False
    difference = None
    if wallet_balance is not None:
        unallocated = round(wallet_balance - allocated, 7)
        difference = 0.0  # wallet = allocated + unallocated by definition during migration
        reconciled = abs(unallocated) < 0.0000001

    return {
        "wallet_label": wallet_label,
        "wallet_address": wallet_address,
        "wallet_balance_pi": round(wallet_balance, 7) if wallet_balance is not None else None,
        "allocated_pi": allocated,
        "unallocated_pi": unallocated,
        "difference_pi": difference,
        "fully_allocated": reconciled,
        "balance_error": balance_error,
        "fund_count": len(funds),
    }


def create_internal_fund_transfer(from_fund_id, to_fund_id, amount_pi, reason):
    from_fund = get_fund(from_fund_id)
    to_fund = get_fund(to_fund_id)

    if not from_fund or not to_fund:
        return {"ok": False, "message": "Fund not found."}

    if str(from_fund_id) == str(to_fund_id):
        return {"ok": False, "message": "Source and destination fund must be different."}

    try:
        amount = round(float(amount_pi), 7)
    except Exception:
        return {"ok": False, "message": "Invalid Pi amount."}

    if amount <= 0:
        return {"ok": False, "message": "Transfer amount must be greater than zero."}

    reason = str(reason or "").strip()
    if not reason:
        return {"ok": False, "message": "Internal fund transfers require a reason."}

    balances = {f.get("id"): f for f in fund_balance_summary()}
    available = float((balances.get(from_fund_id) or {}).get("balance_pi") or 0)

    if amount > available + 0.0000001:
        return {
            "ok": False,
            "message": f"Not enough allocated balance in {from_fund.get('name')}. Available: {available} Pi.",
        }

    transfer_id = f"transfer_{int(time.time() * 1000)}"

    common = {
        "internal_transfer_id": transfer_id,
        "amount_pi": amount,
        "reason": reason,
        "source": "fund_internal_transfer",
        "no_blockchain_movement": True,
    }

    add_fund_ledger_entry({
        **common,
        "direction": "transfer_out",
        "fund_id": from_fund.get("id"),
        "fund_name_snapshot": from_fund.get("name"),
        "counterparty_fund_id": to_fund.get("id"),
        "counterparty_fund_name_snapshot": to_fund.get("name"),
    })

    add_fund_ledger_entry({
        **common,
        "direction": "transfer_in",
        "fund_id": to_fund.get("id"),
        "fund_name_snapshot": to_fund.get("name"),
        "counterparty_fund_id": from_fund.get("id"),
        "counterparty_fund_name_snapshot": from_fund.get("name"),
    })

    return {
        "ok": True,
        "message": f"Transferred {amount} Pi from {from_fund.get('name')} to {to_fund.get('name')} (accounting only).",
        "transfer_id": transfer_id,
    }


def fund_balance_summary():
    funds = load_funds(False)
    ledger = load_fund_ledger().get("entries", [])

    result = []
    for fund in funds:
        fid = fund.get("id")
        incoming = 0.0
        outgoing = 0.0
        transfer_in = 0.0
        transfer_out = 0.0

        for entry in ledger:
            if str(entry.get("fund_id") or "") != str(fid):
                continue
            try:
                amount = float(entry.get("amount_pi") or 0)
            except Exception:
                amount = 0.0

            direction = str(entry.get("direction") or "")
            if direction == "incoming":
                incoming += amount
            elif direction == "outgoing":
                outgoing += amount
            elif direction == "transfer_in":
                transfer_in += amount
            elif direction == "transfer_out":
                transfer_out += amount

        item = dict(fund)
        item.update({
            "incoming_pi": round(incoming, 7),
            "outgoing_pi": round(outgoing, 7),
            "transfer_in_pi": round(transfer_in, 7),
            "transfer_out_pi": round(transfer_out, 7),
            "balance_pi": round(incoming + transfer_in - outgoing - transfer_out, 7),
        })
        result.append(item)

    return result


@app.route("/funds", methods=["GET"])
def funds_home():
    return render_template(
        "funds.html",
        funds=fund_balance_summary(),
        reconciliation=wallet_fund_reconciliation_summary(),
        result=request.args.get("result"),
        message=request.args.get("message"),
    )


@app.route("/funds/transfer", methods=["POST"])
def funds_transfer():
    result = create_internal_fund_transfer(
        request.form.get("from_fund_id"),
        request.form.get("to_fund_id"),
        request.form.get("amount_pi"),
        request.form.get("reason"),
    )

    if result.get("ok"):
        return redirect("/funds?result=transfer_ok&message=" + quote(str(result.get("message") or "")))

    return redirect("/funds?result=transfer_failed&message=" + quote(str(result.get("message") or "")))


@app.route("/funds/create", methods=["POST"])
def funds_create():
    name = str(request.form.get("name") or "").strip()
    description = str(request.form.get("description") or "").strip()
    workflow = str(request.form.get("workflow") or "record_only").strip()
    if workflow not in {"record_only", "planting"}:
        workflow = "record_only"

    if not name:
        return redirect("/funds?result=name_required")

    fund_id = clean_fund_id(request.form.get("fund_id") or name)
    if not fund_id:
        return redirect("/funds?result=invalid_id")

    funds = load_funds(False)
    if any(str(f.get("id") or "") == fund_id for f in funds):
        return redirect("/funds?result=id_exists")

    funds.append({
        "id": fund_id,
        "name": name,
        "fund_type": "cause",
        "workflow": workflow,
        "description": description,
        "status": "active",
        "sort_order": 100 + len(funds),
        "created_at": now_iso(),
    })
    save_funds(funds)
    return redirect("/funds?result=created")


@app.route("/funds/update", methods=["POST"])
def funds_update():
    fund_id = str(request.form.get("fund_id") or "").strip()
    funds = load_funds(False)
    target = next((f for f in funds if str(f.get("id") or "") == fund_id), None)
    if not target:
        return redirect("/funds?result=not_found")

    name = str(request.form.get("name") or "").strip()
    description = str(request.form.get("description") or "").strip()
    status = str(request.form.get("status") or "active").strip()
    if status not in {"active", "closed"}:
        status = "active"

    workflow = str(request.form.get("workflow") or target.get("workflow") or "record_only").strip()
    if workflow not in {"record_only", "planting"}:
        workflow = "record_only"

    if name:
        target["name"] = name
    target["description"] = description
    target["status"] = status
    target["workflow"] = workflow
    target["updated_at"] = now_iso()

    save_funds(funds)
    return redirect("/funds?result=updated")


# ---------------------------------------------------------------------------
# Wallet Watcher — incoming payment classification
# ---------------------------------------------------------------------------

def wallet_classifications_dir():
    path = wallet_watcher_dir() / "classifications"
    path.mkdir(parents=True, exist_ok=True)
    return path


def wallet_classification_file(tx_hash):
    safe = re.sub(r"[^a-zA-Z0-9]", "", str(tx_hash or "")).lower()
    return wallet_classifications_dir() / f"{safe}.json"


def load_wallet_classification(tx_hash):
    if not tx_hash:
        return None
    data = load_json(wallet_classification_file(tx_hash), None)
    return data if isinstance(data, dict) else None


def save_wallet_classification(tx_hash, data):
    payload = dict(data or {})
    payload["schema"] = "tpf_wallet_transaction_classification_v1"
    payload["tx_hash"] = tx_hash
    payload["updated_at"] = now_iso()
    save_json(wallet_classification_file(tx_hash), payload)
    return payload


def attach_wallet_classification(transactions):
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        tx_hash = str(tx.get("tx_hash") or "").strip()
        tx["classification"] = load_wallet_classification(tx_hash)
        tx["mapped_display_name"] = mapped_display_name_for_record(tx)
    return transactions


def process_confirmed_tree_offset_pending(file_name, donation_id):
    """Run the existing donation router immediately after Tree/Offset confirmation."""
    selected_path = PENDING_DIR / file_name
    if not selected_path.exists():
        return "/planting"

    donation = load_json(selected_path, None)
    if not isinstance(donation, dict):
        return "/planting"

    if WORKING_DONATION_FILE.exists():
        try:
            WORKING_DONATION_FILE.unlink()
        except Exception:
            pass

    save_json(WORKING_DONATION_FILE, donation)

    try:
        subprocess.run(
            ["python", str(SCRIPTS_DIR / "process_donation.py")],
            cwd=str(ROOT_DIR)
        )
    finally:
        if WORKING_DONATION_FILE.exists():
            try:
                WORKING_DONATION_FILE.unlink()
            except Exception:
                pass

    if has_donation_completed(donation_id):
        archive_pending_files_for_donation(donation_id)

    return redirect_after_processing(donation_id)


@app.route("/funds/delete", methods=["POST"])
def funds_delete():
    fund_id = str(request.form.get("fund_id") or "").strip()
    confirm_name = str(request.form.get("confirm_name") or "").strip()

    funds = load_funds(False)
    target = next((f for f in funds if str(f.get("id") or "") == fund_id), None)
    if not target:
        return redirect("/funds?result=delete_not_found")

    if str(target.get("fund_type") or "") == "base":
        return redirect("/funds?result=delete_blocked&message=" + quote("Permanent base funds cannot be deleted."))

    if confirm_name != str(target.get("name") or ""):
        return redirect("/funds?result=delete_confirm_failed&message=" + quote("Fund name confirmation did not match."))

    ledger = load_fund_ledger().get("entries", [])
    related = [
        e for e in ledger
        if isinstance(e, dict)
        and (
            str(e.get("fund_id") or "") == fund_id
            or str(e.get("counterparty_fund_id") or "") == fund_id
        )
    ]

    if related:
        return redirect("/funds?result=delete_blocked&message=" + quote(
            "This fund has financial history and cannot be deleted. Close/archive it instead."
        ))

    save_funds([f for f in funds if str(f.get("id") or "") != fund_id])
    return redirect("/funds?result=deleted&message=" + quote(
        f"Deleted empty cause fund: {target.get('name')}"
    ))


@app.route("/wallet-watcher/classify", methods=["POST"])
def wallet_watcher_classify():
    tx_hash = str(request.form.get("tx_hash") or "").strip()
    if not tx_hash:
        return redirect("/wallet-watcher?classify=missing_tx")

    classification = str(request.form.get("classification") or "").strip()
    note = str(request.form.get("note") or "").strip()

    if not classification:
        return redirect("/wallet-watcher?classify=missing_classification")

    # Partner payments are confirmed and booked together from the selected order.
    # Selecting this option must not create a regular planting contribution.
    if classification == "partner_pool_payments":
        return redirect(url_for("partner_portal_inbox", payment_tx=tx_hash.lower()))
    existing_classification = load_wallet_classification(tx_hash)
    if existing_classification and existing_classification.get("partner_request_id"):
        return "This payment belongs to a partner order. Review its audit record before any correction.", 409

    display_name = str(request.form.get("display_name") or "").strip()
    from_address = str(request.form.get("from_address") or "").strip()
    to_address = str(request.form.get("to_address") or "").strip()
    amount_pi = request.form.get("amount_pi")
    source_id = str(request.form.get("source_id") or "").strip()
    source_label = str(request.form.get("source_label") or "").strip()
    created_at = str(request.form.get("created_at") or "").strip()
    operation_id = str(request.form.get("operation_id") or "").strip()

    if not display_name:
        display_name = mapped_display_name_for_record({"from_address": from_address}) or "Arboris"

    remember_mapping = bool(request.form.get("remember_wallet_mapping"))
    if remember_mapping and from_address and display_name and display_name != "Arboris":
        save_wallet_display_mapping(
            from_address,
            display_name,
            f"Confirmed from Wallet Watcher fund assignment."
        )

    # Operational classifications that are not funds.
    if classification in {"__internal_transfer__", "__ignore__"}:
        label = "Internal Transfer" if classification == "__internal_transfer__" else "Ignore / Not a donation"
        save_wallet_classification(tx_hash, {
            "classification": classification,
            "classification_label": label,
            "note": note,
            "display_name": display_name,
            "from_address": from_address,
            "to_address": to_address,
            "amount_pi": amount_pi,
            "operation_id": operation_id,
            "source_id": source_id,
            "source_label": source_label,
            "created_at_chain": created_at,
            "remember_wallet_mapping": remember_mapping,
            "confirmed_at": now_iso(),
            "status": "confirmed_non_fund",
        })
        return redirect("/wallet-watcher?classify=saved_non_fund")

    fund = get_fund(classification)
    if not fund or str(fund.get("status") or "") != "active":
        return redirect("/wallet-watcher?classify=invalid_fund")

    classification_record = save_wallet_classification(tx_hash, {
        "classification": "fund",
        "fund_id": fund.get("id"),
        "fund_name": fund.get("name"),
        "fund_type": fund.get("fund_type"),
        "fund_workflow": fund.get("workflow"),
        "fund_description_snapshot": fund.get("description"),
        "note": note,
        "display_name": display_name,
        "from_address": from_address,
        "to_address": to_address,
        "amount_pi": amount_pi,
        "operation_id": operation_id,
        "source_id": source_id,
        "source_label": source_label,
        "created_at_chain": created_at,
        "remember_wallet_mapping": remember_mapping,
        "confirmed_at": now_iso(),
        "status": "fund_confirmed",
    })

    add_fund_ledger_entry({
        "direction": "incoming",
        "fund_id": fund.get("id"),
        "fund_name_snapshot": fund.get("name"),
        "fund_type_snapshot": fund.get("fund_type"),
        "amount_pi": amount_pi,
        "tx_hash": tx_hash,
        "operation_id": operation_id,
        "wallet_address": from_address,
        "display_name": display_name,
        "note": note,
        "chain_created_at": created_at,
        "source": "wallet_watcher",
    })

    # Reforestation/CO2 is the only initial fund that hands off to planting.
    if str(fund.get("workflow") or "") != "planting":
        classification_record["status"] = "fund_recorded"
        save_wallet_classification(tx_hash, classification_record)
        return redirect("/wallet-watcher?classify=fund_recorded")

    tx = {
        "tx_hash": tx_hash,
        "amount_pi": amount_pi,
        "from_address": from_address,
        "to_address": to_address,
        "operation_id": operation_id,
        "source_id": source_id,
        "source_label": source_label,
        "network": "mainnet",
        "direction": "incoming",
        "created_at_chain": created_at,
        "blockchain_checked": True,
        "blockchain_verified": True,
    }

    result = create_pending_donation_from_wallet_tx(
        tx,
        purpose_reason=note or fund.get("name"),
        classification="tree_offset",
    )

    if not result.get("ok"):
        classification_record["status"] = "fund_recorded_pending_create_failed"
        classification_record["error"] = result.get("message")
        save_wallet_classification(tx_hash, classification_record)
        return redirect("/wallet-watcher?classify=pending_failed")

    classification_record["pending_donation_file"] = result.get("file")
    classification_record["donation_id"] = result.get("donation_id")
    classification_record["status"] = "tree_offset_confirmed_pending_next_step"
    save_wallet_classification(tx_hash, classification_record)

    return redirect("/planting")


def auto_create_pending_donations_from_wallet_transactions(transactions):
    """Legacy compatibility helper — intentionally disabled.

    Incoming wallet payments must now be identified, classified and given a
    reason before any pending donation is created.
    """
    for tx in transactions or []:
        if isinstance(tx, dict):
            tx["pending_donation_exists"] = False
            tx["pending_donation_file"] = None
    return {
        "enabled": False,
        "created_count": 0,
        "created": [],
        "skipped_count": 0,
        "skipped": [],
        "message": "Automatic pending-donation creation is disabled. Classify the payment first."
    }


@app.route("/wallet-watcher/backfill", methods=["POST"])
def wallet_watcher_backfill():
    result = wallet_watcher_backfill_all()
    return redirect(
        "/wallet-watcher?backfill=done"
        f"&added={result.get('archive_added', 0)}"
        f"&total={result.get('archive_total_after', 0)}"
        f"&pages={result.get('pages_checked', 0)}"
        f"&errors={len(result.get('errors', []))}"
    )


@app.route("/wallet-watcher/backup", methods=["POST"])
def wallet_watcher_backup():
    result = create_wallet_backup()
    copied = len(result.get("copied_files", []))
    return redirect(f"/wallet-watcher?backup=created&copied={copied}")


def update_wallet_master_transaction_status(tx_hash, new_status):
    """
    Update review status inside transactions_master.json only.
    This never deletes transactions and never touches the raw blockchain archive.
    """
    allowed = {"unmatched_blockchain", "ignored_manual"}
    if new_status not in allowed:
        return {"ok": False, "message": "Invalid status."}

    tx_hash_clean = (tx_hash or "").lower().strip()
    if not tx_hash_clean:
        return {"ok": False, "message": "Missing transaction hash."}

    master = load_wallet_master()
    records = master.get("transactions", []) if isinstance(master, dict) else []
    if not isinstance(records, list):
        return {"ok": False, "message": "Master ledger has no transaction list."}

    for record in records:
        if not isinstance(record, dict):
            continue
        if (record.get("tx_hash") or "").lower().strip() != tx_hash_clean:
            continue

        old_status = record.get("history_match_status")

        # Safety: only allow toggling review/ignored states.
        # Never overwrite matched historical records here.
        if old_status not in ["unmatched_blockchain", "ignored_manual", "ignored_test_payment"]:
            return {"ok": False, "message": f"Status not changed. Current status is protected: {old_status}"}

        if old_status == "ignored_test_payment" and new_status == "ignored_manual":
            return {"ok": False, "message": "Test ignored entries are protected from manual ignored status."}

        record["history_match_status"] = new_status
        record["manual_review"] = {
            "status": new_status,
            "previous_status": old_status,
            "updated_at": now_iso(),
            "updated_by": "TPF Operations Center",
            "note": "Manual Wallet Ledger review status change. Raw blockchain archive unchanged."
        }

        master["updated_at"] = now_iso()
        master["update_note"] = "Wallet Ledger manual review status update."
        save_json(wallet_master_file(), master)
        return {"ok": True, "message": f"Status changed from {old_status} to {new_status}."}

    return {"ok": False, "message": "Transaction not found in master ledger."}


@app.route("/wallet-watcher/ledger/status", methods=["POST"])
def wallet_watcher_ledger_status():
    tx_hash = request.form.get("tx_hash", "")
    action = request.form.get("action", "")

    if action == "ignore":
        new_status = "ignored_manual"
    elif action == "return_to_review":
        new_status = "unmatched_blockchain"
    else:
        return redirect("/wallet-watcher/ledger?status_update=invalid")

    result = update_wallet_master_transaction_status(tx_hash, new_status)
    if result.get("ok"):
        return redirect("/wallet-watcher/ledger?status_update=ok")
    return redirect("/wallet-watcher/ledger?status_update=failed")


@app.route("/wallet-watcher/ledger")
def wallet_watcher_ledger():
    master_summary = wallet_master_ui_summary()
    transactions = wallet_master_all_transactions()
    workflow_only_items = workflow_items_not_in_master()

    return render_template(
        "wallet_ledger.html",
        master_summary=master_summary,
        transactions=transactions,
        workflow_only_items=workflow_only_items
    )


def wallet_workflow_by_tx_hash():
    """Map blockchain TX hashes to the current TPF donation workflow state.

    This is UI glue only. It lets Wallet Watcher show that a transaction has already
    moved to pending, suggestions, planting confirmation, planted, or pool-covered
    instead of repeating stale "Needs review / pending created" text.
    """
    lookup = {}

    for item in build_donation_flow_items():
        tx_hash = (item.get("tx_hash") or "").lower().strip()
        if not tx_hash or tx_hash == "—":
            continue

        lookup[tx_hash] = {
            "donation_id": item.get("donation_id"),
            "amount_pi": item.get("amount_pi"),
            "donor": item.get("donor"),
            "route": item.get("route"),
            "status": item.get("status"),
            "status_badge": item.get("status_badge", {}),
            "next_action": item.get("next_action"),
            "technical_file": item.get("technical_file"),
            "source": item.get("source"),
            "detail_href": item.get("detail_href"),
            "date": item.get("date"),
        }

    return lookup


def attach_wallet_workflow_status(transactions):
    workflow_lookup = wallet_workflow_by_tx_hash()

    for tx in transactions:
        if not isinstance(tx, dict):
            continue

        tx_hash = (tx.get("tx_hash") or "").lower().strip()
        workflow = workflow_lookup.get(tx_hash)

        tx["workflow_found"] = bool(workflow)
        tx["workflow"] = workflow or None

        # If the transaction exists anywhere in the TPF workflow, it is no longer
        # just an unmatched raw wallet payment from an operator perspective.
        if workflow:
            tx["operator_status_label"] = workflow.get("status_badge", {}).get("label") or workflow.get("status") or "In TPF workflow"
            tx["operator_status_class"] = workflow.get("status_badge", {}).get("class") or "matched-label"
        else:
            tx["operator_status_label"] = None
            tx["operator_status_class"] = None

        tx["can_create_pending"] = (
            tx.get("direction") == "incoming"
            and not tx.get("workflow_found")
            and not tx.get("pending_donation_exists")
            and tx.get("master_match_status") not in ["matched_history", "ignored_test_payment", "ignored_manual"]
        )

    return transactions


def workflow_items_not_in_master():
    """Donation workflow records whose TX hash is not represented in transactions_master.json.

    The master ledger is a historical baseline. New live donations can be in the TPF
    workflow before they are added to that baseline, so show them explicitly to avoid
    the confusing impression that they are missing.
    """
    master_lookup = wallet_master_by_tx_hash()
    items = []

    for item in build_donation_flow_items():
        tx_hash = (item.get("tx_hash") or "").lower().strip()
        if not tx_hash or tx_hash == "—":
            continue
        if tx_hash in master_lookup:
            continue
        items.append(item)

    return items


@app.route("/wallet-watcher")
def wallet_watcher():
    sources, transactions, fetch_errors = wallet_watcher_fetch_all(limit=10)
    transactions = enrich_wallet_transactions_with_master(transactions)
    # Classification is now mandatory before a new incoming payment enters the donation workflow.
    # Merely refreshing Wallet Watcher must never create a pending planting donation.
    auto_import_result = {
        "enabled": False,
        "created_count": 0,
        "message": "Automatic pending-donation creation is disabled. Identify, classify and give a reason first."
    }
    transactions = attach_wallet_workflow_status(transactions)
    transactions = attach_wallet_classification(transactions)
    master_summary = wallet_master_ui_summary()
    unmatched_transactions = wallet_master_unmatched_transactions()
    archive_summary = wallet_blockchain_archive_summary()

    last_fetch = load_json(wallet_transactions_file(), {})
    last_checked = last_fetch.get("fetched_at", "Not checked yet") if isinstance(last_fetch, dict) else "Not checked yet"

    backup_result = None
    if request.args.get("backup") == "created":
        backup_result = {
            "ok": True,
            "message": f"Wallet backup created. Files copied: {request.args.get('copied', '0')}."
        }

    backfill_result = None
    if request.args.get("backfill") == "done":
        backfill_result = {
            "ok": request.args.get("errors", "0") == "0",
            "message": (
                f"Wallet archive backfill completed. "
                f"Added: {request.args.get('added', '0')} · "
                f"Archive total: {request.args.get('total', '0')} · "
                f"Pages checked: {request.args.get('pages', '0')} · "
                f"Errors: {request.args.get('errors', '0')}."
            )
        }

    return render_template(
        "wallet_watcher.html",
        sources=sources,
        transactions=transactions,
        fetch_errors=fetch_errors,
        master_summary=master_summary,
        unmatched_transactions=unmatched_transactions,
        archive_summary=archive_summary,
        backup_result=backup_result,
        backfill_result=backfill_result,
        auto_import_result=auto_import_result,
        last_checked=last_checked,
        funds=load_funds(active_only=True),
        fund_summary=fund_balance_summary(),
        reconciliation=wallet_fund_reconciliation_summary()
    )


# ---------------------------------------------------------------------------
# Project Library — Project Intelligence viewer
# ---------------------------------------------------------------------------

def project_intelligence_dir():
    return DATA_ROOT / "project-intelligence"


def project_profiles_dir():
    return project_intelligence_dir() / "profiles"


def project_content_dir():
    return project_intelligence_dir() / "content"


def project_library_profile_id(path):
    match = re.search(r"project_(\d+)_profile\.json$", path.name)
    return match.group(1) if match else path.stem


def clean_project_country(profile):
    country = profile.get("country")
    if isinstance(country, dict):
        return country.get("name") or country.get("code") or "—"
    return str(country or "—")


def load_project_profile(project_id):
    path = project_profiles_dir() / f"project_{project_id}_profile.json"
    data = load_json(path, None)
    return data if isinstance(data, dict) else None


def load_project_content(project_id):
    path = project_content_dir() / f"project_{project_id}_content.json"
    data = load_json(path, None)
    return data if isinstance(data, dict) else None


def load_project_library_items():
    items = []
    profiles_dir = project_profiles_dir()
    if not profiles_dir.exists():
        return items

    for path in sorted(profiles_dir.glob("project_*_profile.json")):
        profile = load_json(path, {}) or {}
        if not isinstance(profile, dict):
            continue

        project_id = str(profile.get("project_id") or project_library_profile_id(path))
        impact = profile.get("tpf_impact", {}) if isinstance(profile.get("tpf_impact"), dict) else {}
        tree_nation = profile.get("tree_nation", {}) if isinstance(profile.get("tree_nation"), dict) else {}
        species = profile.get("species", {}) if isinstance(profile.get("species"), dict) else {}
        official_update = profile.get("official_update_snapshot", {}) if isinstance(profile.get("official_update_snapshot"), dict) else {}
        manual_review = profile.get("manual_review", {}) if isinstance(profile.get("manual_review"), dict) else {}
        plain = profile.get("plain_language", {}) if isinstance(profile.get("plain_language"), dict) else {}

        items.append({
            "project_id": project_id,
            "project_name": profile.get("project_name") or f"Project {project_id}",
            "country": clean_project_country(profile),
            "trees": impact.get("trees", 0),
            "co2_kg": impact.get("co2_kg", 0),
            "certificates": impact.get("certificates", 0),
            "species_used": impact.get("species") or species.get("used_by_tpf") or [],
            "available_species": species.get("available_count", tree_nation.get("species_available", 0)),
            "project_url": tree_nation.get("project_url") or official_update.get("source_url"),
            "latest_update_title": official_update.get("title", ""),
            "summary": plain.get("summary", ""),
            "review_status": manual_review.get("review_status", "needs_review"),
            "detail_href": f"/project-library/project/{project_id}",
        })

    items.sort(key=lambda item: str(item.get("project_name", "")).lower())
    return items


@app.route("/project-library")
def project_library():
    projects = load_project_library_items()
    totals = {
        "projects": len(projects),
        "trees": sum(float(item.get("trees") or 0) for item in projects),
        "co2_kg": sum(float(item.get("co2_kg") or 0) for item in projects),
        "certificates": sum(float(item.get("certificates") or 0) for item in projects),
    }
    return render_template("project_library.html", projects=projects, totals=totals, selected=None, content=None)


@app.route("/project-library/project/<project_id>")
def project_library_detail(project_id):
    projects = load_project_library_items()
    profile = load_project_profile(project_id)
    content = load_project_content(project_id)

    if not profile:
        return workflow_stop_page(
            "Project profile not found",
            f"No Project Intelligence profile found for project ID: <b>{project_id}</b>",
            primary_link="/project-library",
            primary_label="Back to Project Library"
        )

    return render_template("project_library.html", projects=projects, totals=None, selected=profile, content=content)






# ---------------------------------------------------------------------------
# Posts & Communication — core storage helpers v2.2
# ---------------------------------------------------------------------------

def posts_root_dir():
    path = DATA_ROOT / "posts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def post_actions_dir():
    path = posts_root_dir() / "actions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def post_action_file(action_id):
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(action_id or "unknown"))
    return post_actions_dir() / f"{safe_id}.json"


def post_action_id(source_type, source_id, action_kind):
    raw = f"{source_type}_{source_id}_{action_kind}"
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)


# ---------------------------------------------------------------------------
# Posts & Communication — drafts v2
# ---------------------------------------------------------------------------

def post_drafts_dir():
    path = posts_root_dir() / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def post_draft_file(action_id):
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(action_id or "unknown"))
    return post_drafts_dir() / f"{safe_id}.json"


def _post_record_lookup(donation_id):
    for record in build_donation_flow_items():
        if record.get("donation_id") == donation_id:
            return record
    return None


def _post_source_timestamp(record):
    if not isinstance(record, dict):
        return 0
    try:
        return float(record.get("timestamp") or 0)
    except Exception:
        return 0


def sync_post_actions_from_completed_donations():
    created = 0

    for record in build_donation_flow_items():
        if record.get("status") not in ["planted", "covered_by_pool"]:
            continue

        donation_id = record.get("donation_id")
        if not donation_id or donation_id == "unknown":
            continue

        source_summary = {
            "display_name": record.get("display_name") or record.get("donor"),
            "amount_pi": record.get("amount_pi"),
            "route": record.get("route"),
            "date": record.get("date"),
            "source_timestamp": _post_source_timestamp(record),
            "tx_hash": record.get("tx_hash"),
            "record_href": record.get("detail_href") or f"/record/{donation_id}",
        }

        definitions = [
            (
                "official_tpf_channel",
                "required",
                "ThePioneerForest",
                "Official ThePioneerForest channel post",
            ),
            (
                "aiart_support",
                "recommended",
                "AiArt",
                "Supporting AiArt post",
            ),
        ]

        for action_kind, priority, channel, title in definitions:
            action_id = post_action_id("donation", donation_id, action_kind)
            path = post_action_file(action_id)
            existed = path.exists()

            action = load_json(path, {}) if existed else {}
            if not isinstance(action, dict):
                action = {}

            if not existed:
                action = {
                    "schema": "tpf_post_action_v1",
                    "action_id": action_id,
                    "created_at": now_iso(),
                    "status": "open",
                    "draft_id": None,
                    "published_url": "",
                    "published_at": None,
                    "notes": "",
                }
                created += 1

            # Refresh factual source data every sync. Do not overwrite workflow state.
            action.update({
                "updated_at": now_iso(),
                "source_type": "donation",
                "source_id": donation_id,
                "action_kind": action_kind,
                "priority": priority,
                "channel": channel,
                "title": title,
                "source_summary": source_summary,
            })
            save_json(path, action)

    return created


def load_post_actions():
    sync_post_actions_from_completed_donations()
    actions = []

    for item in load_json_files(post_actions_dir()):
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue

        action = dict(data)
        action["file"] = item.get("file")
        action["modified"] = item.get("modified", 0)
        source_summary = action.get("source_summary", {}) if isinstance(action.get("source_summary"), dict) else {}
        action["record_href"] = source_summary.get("record_href") or (
            f"/record/{action.get('source_id')}" if action.get("source_type") == "donation" else None
        )
        action["source_timestamp"] = source_summary.get("source_timestamp") or 0
        action["draft_exists"] = post_draft_file(action.get("action_id")).exists()
        actions.append(action)

    # Newest source event first. Priority is only a secondary sort.
    priority_order = {"required": 0, "recommended": 1, "optional": 2}
    actions.sort(
        key=lambda a: (
            -(float(a.get("source_timestamp") or 0)),
            priority_order.get(a.get("priority"), 9),
            a.get("title") or "",
        )
    )
    return actions


def _knowledge_matches_for_post(project_name="", species_name="", limit=5):
    terms = [
        str(project_name or "").strip().lower(),
        str(species_name or "").strip().lower(),
    ]
    terms = [t for t in terms if t]
    if not terms:
        return []

    matches = []
    for item in load_knowledge_index():
        article = load_knowledge_article(item.get("id"))
        body = article.get("body", "") if article else ""
        haystack = " ".join([
            str(item.get("title") or ""),
            str(item.get("category") or ""),
            " ".join(item.get("tags") or []),
            body,
        ]).lower()

        score = sum(1 for term in terms if term in haystack)
        if score:
            matches.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "category": item.get("category"),
                "score": score,
            })

    matches.sort(key=lambda m: (-m["score"], str(m.get("title") or "").lower()))
    return matches[:limit]


def _proof_summary_for_post(donation_id):
    proofs = tree_nation_proofs_for_donation(donation_id)
    return proofs[0] if proofs else {}


def _official_post_default(record, proof):
    display_name = str(record.get("display_name") or record.get("donor") or "Arboris").strip() or "Arboris"
    amount_pi = record.get("amount_pi", "—")
    project = proof.get("project_name") or "a Tree-Nation project"
    species = proof.get("species_name") or "trees"
    quantity = proof.get("quantity") or "—"
    co2 = proof.get("total_co2_kg") or "—"
    tree_url = proof.get("tree_url") or ""
    certificate_url = proof.get("certificate_url") or ""

    title = f"{quantity} Trees Take Root at Mt. Elgon 🌱" if "Mt. Elgon" in str(project) else f"{quantity} New Trees Take Root 🌱"
    title = title[:80]

    lines = [
        f"{display_name} has helped another piece of The Pioneer Forest take root.",
        "",
        f"{amount_pi} Pi → {quantity} {species} tree{'s' if str(quantity) != '1' else ''}",
        f"Project: {project}",
        f"Impact: {co2} kg CO₂",
    ]

    if tree_url:
        lines.extend(["", f"Tree: {tree_url}"])
    if certificate_url:
        lines.append(f"Certificate: {certificate_url}")

    lines.extend([
        "",
        "Go Pi. Go Green. Go The Pioneer Forest.",
        "#ThePioneerForest",
    ])

    return title, "\n".join(lines)


def _aiart_post_default(record, proof):
    display_name = str(record.get("display_name") or record.get("donor") or "Arboris").strip() or "Arboris"
    project = proof.get("project_name") or "The Pioneer Forest"
    species = proof.get("species_name") or "new trees"
    quantity = proof.get("quantity") or "—"
    co2 = proof.get("total_co2_kg") or "—"

    title = f"Roots from Pi — {quantity} More Trees 🌱"[:80]
    body = (
        f"From Pi to roots. 🌱\n\n"
        f"{display_name} helped turn support into {quantity} {species} tree{'s' if str(quantity) != '1' else ''} "
        f"for {project} — {co2} kg CO₂ added to The Pioneer Forest.\n\n"
        f"A small digital action. A real place. Real trees.\n\n"
        f"#ThePioneerForest"
    )

    image_brief = (
        "Create a TPF-style AiArt image using only the core verified facts: "
        f"{quantity} {species} trees, {project}, {co2} kg CO₂, and The Pioneer Forest. "
        "No invented logos, certificates, maps, people, or unverified project details. "
        "Keep the visual artistic rather than infographic-heavy; include The Pioneer Forest name clearly."
    )

    return title, body, image_brief


def build_post_draft(action):
    if not isinstance(action, dict):
        return None

    action_id = action.get("action_id")
    donation_id = action.get("source_id")
    record = _post_record_lookup(donation_id) or {}
    proof = _proof_summary_for_post(donation_id)

    if action.get("action_kind") == "official_tpf_channel":
        title, body = _official_post_default(record, proof)
        image_brief = ""
    else:
        title, body, image_brief = _aiart_post_default(record, proof)

    knowledge_matches = _knowledge_matches_for_post(
        proof.get("project_name"),
        proof.get("species_name"),
    )

    return {
        "schema": "tpf_post_draft_v1",
        "draft_id": action_id,
        "action_id": action_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source_type": action.get("source_type"),
        "source_id": donation_id,
        "channel": action.get("channel"),
        "priority": action.get("priority"),
        "action_kind": action.get("action_kind"),
        "title": title,
        "body": body,
        "image_brief": image_brief,
        "facts": {
            "display_name": record.get("display_name") or record.get("donor"),
            "amount_pi": record.get("amount_pi"),
            "route": record.get("route"),
            "tx_hash": record.get("tx_hash"),
            "project_name": proof.get("project_name"),
            "species_name": proof.get("species_name"),
            "quantity": proof.get("quantity"),
            "co2_kg": proof.get("total_co2_kg"),
            "tree_url": proof.get("tree_url"),
            "certificate_url": proof.get("certificate_url"),
        },
        "knowledge_matches": knowledge_matches,
        "generation_note": (
            "Draft generated from current Records + Project Intelligence facts. "
            "Knowledge Center matches are referenced when available; no unsupported facts are invented."
        ),
    }


def load_or_create_post_draft(action_id):
    action = load_json(post_action_file(action_id), None)
    if not isinstance(action, dict):
        return None, None

    path = post_draft_file(action_id)
    draft = load_json(path, None)
    if not isinstance(draft, dict):
        draft = build_post_draft(action)
        if draft:
            save_json(path, draft)

    return action, draft


@app.route("/posts/action/<action_id>/draft")
def post_action_draft(action_id):
    action, draft = load_or_create_post_draft(action_id)
    if not action or not draft:
        return redirect("/posts")

    return render_template(
        "post_draft.html",
        action=action,
        draft=draft,
    )


@app.route("/posts/action/<action_id>/draft/save", methods=["POST"])
def save_post_action_draft(action_id):
    action, draft = load_or_create_post_draft(action_id)
    if not action or not draft:
        return redirect("/posts")

    draft["title"] = str(request.form.get("title") or "").strip()
    draft["body"] = str(request.form.get("body") or "").strip()
    draft["image_brief"] = str(request.form.get("image_brief") or "").strip()
    draft["updated_at"] = now_iso()
    save_json(post_draft_file(action_id), draft)

    action["status"] = "draft"
    action["draft_id"] = action_id
    action["updated_at"] = now_iso()
    save_json(post_action_file(action_id), action)

    return redirect(f"/posts/action/{action_id}/draft?saved=1")




def posts_summary():
    actions = load_post_actions()
    return {
        "total": len(actions),
        "open_required": sum(1 for a in actions if a.get("status") in ["open", "draft"] and a.get("priority") == "required"),
        "open_recommended": sum(1 for a in actions if a.get("status") in ["open", "draft"] and a.get("priority") == "recommended"),
        "drafts": sum(1 for a in actions if a.get("status") == "draft"),
        "published": sum(1 for a in actions if a.get("status") == "published"),
    }


def add_posts_to_overview_actions(actions, summary):
    actions = list(actions or [])
    if summary.get("open_required", 0) > 0:
        actions.append({
            "level": "warning",
            "title": "Official ThePioneerForest post required",
            "message": f"{summary.get('open_required', 0)} required post action(s) are waiting.",
            "href": "/posts",
            "button": "Open Posts & Communication"
        })
    return actions


@app.route("/posts")
def posts_home():
    actions = load_post_actions()
    summary = posts_summary()
    active_actions = [a for a in actions if a.get("status") in ["open", "draft"]]
    published_actions = [a for a in actions if a.get("status") == "published"]

    return render_template(
        "posts.html",
        actions=active_actions,
        published_actions=published_actions,
        summary=summary,
    )



# ---------------------------------------------------------------------------
# Knowledge Center v0.1
# ---------------------------------------------------------------------------

KNOWLEDGE_CATEGORIES = [
    "Documentation",
    "FAQ",
    "Team",
    "Procedures",
    "Cooperation",
    "Other",
]


def knowledge_dir():
    path = DATA_ROOT / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_articles_dir():
    path = knowledge_dir() / "articles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_index_file():
    """
    Normal path is data/mainnet/knowledge/articles.json.

    If articles.json was accidentally created as a folder, keep it untouched and
    use index.json instead. This makes Sprint 1 usable without deleting anything.
    """
    preferred = knowledge_dir() / "articles.json"
    if preferred.exists() and preferred.is_dir():
        return knowledge_dir() / "index.json"
    return preferred


def knowledge_slug(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or f"article-{int(time.time())}"


def load_knowledge_index():
    index_file = knowledge_index_file()
    data = load_json(index_file, [])

    if not isinstance(data, list):
        data = []

    cleaned = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            cleaned.append(item)

    return cleaned


def save_knowledge_index(items):
    save_json(knowledge_index_file(), items)


def knowledge_article_file(article_id):
    safe_id = knowledge_slug(article_id)
    return knowledge_articles_dir() / f"{safe_id}.md"


def load_knowledge_article(article_id):
    article_id = knowledge_slug(article_id)
    metadata = None

    for item in load_knowledge_index():
        if str(item.get("id")) == article_id:
            metadata = dict(item)
            break

    if not metadata:
        return None

    path = knowledge_article_file(article_id)
    body = ""
    if path.exists() and path.is_file():
        try:
            body = path.read_text(encoding="utf-8")
        except Exception:
            body = ""

    metadata["body"] = body
    metadata["file_path"] = str(path)
    return metadata


def markdown_to_safe_html(markdown_text):
    """
    Small built-in Markdown renderer for Sprint 1.
    Supports headings, lists, blockquotes, bold, italic, inline code and links.
    Raw HTML is escaped.
    """
    text = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    html = []
    in_ul = False
    in_ol = False
    paragraph = []

    def inline_format(value):
        value = str(escape(value))
        value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
        value = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
            value,
        )
        return value

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            joined = " ".join(part.strip() for part in paragraph if part.strip())
            if joined:
                html.append(f"<p>{inline_format(joined)}</p>")
            paragraph = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html.append("</ul>")
            in_ul = False
        if in_ol:
            html.append("</ol>")
            in_ol = False

    for raw_line in lines:
        line = raw_line.rstrip()

        if not line.strip():
            flush_paragraph()
            close_lists()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_lists()
            level = len(heading.group(1))
            html.append(f"<h{level}>{inline_format(heading.group(2))}</h{level}>")
            continue

        if line.startswith("> "):
            flush_paragraph()
            close_lists()
            html.append(f"<blockquote>{inline_format(line[2:])}</blockquote>")
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        if unordered:
            flush_paragraph()
            if in_ol:
                html.append("</ol>")
                in_ol = False
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            html.append(f"<li>{inline_format(unordered.group(1))}</li>")
            continue

        ordered = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if ordered:
            flush_paragraph()
            if in_ul:
                html.append("</ul>")
                in_ul = False
            if not in_ol:
                html.append("<ol>")
                in_ol = True
            html.append(f"<li>{inline_format(ordered.group(1))}</li>")
            continue

        paragraph.append(line)

    flush_paragraph()
    close_lists()
    return Markup("\n".join(html))


def knowledge_summary():
    articles = load_knowledge_index()
    categories = sorted({str(item.get("category") or "Other") for item in articles})
    return {
        "articles": len(articles),
        "categories": len(categories),
        "latest_updated": max(
            (str(item.get("updated_at") or item.get("created_at") or "") for item in articles),
            default="—",
        ),
    }


def prepare_knowledge_items(search_text="", category=""):
    search_text = str(search_text or "").strip().lower()
    category = str(category or "").strip()
    items = []

    for raw in load_knowledge_index():
        item = dict(raw)
        article = load_knowledge_article(item.get("id"))
        body = article.get("body", "") if article else ""
        item["body_preview"] = re.sub(r"\s+", " ", body).strip()[:220]
        item["tags_text"] = ", ".join(item.get("tags") or [])
        item["detail_href"] = f"/knowledge/article/{item.get('id')}"
        item["edit_href"] = f"/knowledge/article/{item.get('id')}/edit"

        haystack = " ".join([
            str(item.get("title") or ""),
            str(item.get("category") or ""),
            item["tags_text"],
            body,
        ]).lower()

        if search_text and search_text not in haystack:
            continue
        if category and str(item.get("category") or "") != category:
            continue

        items.append(item)

    items.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return items


def unique_knowledge_id(title, existing_id=None):
    base = knowledge_slug(title)
    candidate = base
    used = {str(item.get("id")) for item in load_knowledge_index()}

    if existing_id:
        used.discard(str(existing_id))

    number = 2
    while candidate in used:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def save_knowledge_article_from_form(form, existing_id=None):
    title = str(form.get("title") or "").strip()
    category = str(form.get("category") or "Other").strip()
    tags_raw = str(form.get("tags") or "")
    body = str(form.get("body") or "")

    if not title:
        return {"ok": False, "message": "Title is required.", "article_id": existing_id}

    if category not in KNOWLEDGE_CATEGORIES:
        category = "Other"

    tags = []
    for tag in tags_raw.split(","):
        clean = tag.strip()
        if clean and clean.lower() not in [existing.lower() for existing in tags]:
            tags.append(clean)

    now = now_iso()
    index = load_knowledge_index()

    if existing_id:
        article_id = knowledge_slug(existing_id)
        existing = next((item for item in index if str(item.get("id")) == article_id), None)
        if not existing:
            return {"ok": False, "message": "Article not found.", "article_id": article_id}

        existing.update({
            "title": title,
            "category": category,
            "tags": tags,
            "updated_at": now,
            "file": f"{article_id}.md",
        })
    else:
        article_id = unique_knowledge_id(title)
        index.append({
            "schema": "tpf_knowledge_article_v1",
            "id": article_id,
            "title": title,
            "category": category,
            "tags": tags,
            "created_at": now,
            "updated_at": now,
            "file": f"{article_id}.md",
        })

    knowledge_article_file(article_id).write_text(body, encoding="utf-8")
    save_knowledge_index(index)

    return {"ok": True, "message": "Article saved.", "article_id": article_id}


@app.route("/knowledge")
def knowledge_home():
    search_text = request.args.get("q", "")
    category = request.args.get("category", "")
    articles = prepare_knowledge_items(search_text, category)
    return render_template(
        "knowledge.html",
        articles=articles,
        summary=knowledge_summary(),
        categories=KNOWLEDGE_CATEGORIES,
        search_text=search_text,
        selected_category=category,
        index_file=str(knowledge_index_file()),
    )


@app.route("/knowledge/new", methods=["GET", "POST"])
def knowledge_new():
    result = None
    article = {
        "title": "",
        "category": "Documentation",
        "tags_text": "",
        "body": "",
    }

    if request.method == "POST":
        article = {
            "title": request.form.get("title", ""),
            "category": request.form.get("category", "Other"),
            "tags_text": request.form.get("tags", ""),
            "body": request.form.get("body", ""),
        }
        result = save_knowledge_article_from_form(request.form)
        if result.get("ok"):
            return redirect(f"/knowledge/article/{result.get('article_id')}?saved=1")

    return render_template(
        "knowledge_form.html",
        mode="new",
        article=article,
        categories=KNOWLEDGE_CATEGORIES,
        result=result,
    )


@app.route("/knowledge/article/<article_id>")
def knowledge_article(article_id):
    article = load_knowledge_article(article_id)
    if not article:
        return workflow_stop_page(
            "Knowledge article not found",
            f"No Knowledge Center article found for ID: <b>{escape(article_id)}</b>",
            primary_link="/knowledge",
            primary_label="Back to Knowledge Center",
        )

    article["rendered_body"] = markdown_to_safe_html(article.get("body", ""))
    return render_template(
        "knowledge_article.html",
        article=article,
        saved=request.args.get("saved") == "1",
    )


@app.route("/knowledge/article/<article_id>/edit", methods=["GET", "POST"])
def knowledge_edit(article_id):
    article = load_knowledge_article(article_id)
    if not article:
        return workflow_stop_page(
            "Knowledge article not found",
            f"No Knowledge Center article found for ID: <b>{escape(article_id)}</b>",
            primary_link="/knowledge",
            primary_label="Back to Knowledge Center",
        )

    result = None
    if request.method == "POST":
        result = save_knowledge_article_from_form(request.form, existing_id=article_id)
        if result.get("ok"):
            return redirect(f"/knowledge/article/{article_id}?saved=1")

        article.update({
            "title": request.form.get("title", article.get("title", "")),
            "category": request.form.get("category", article.get("category", "Other")),
            "tags_text": request.form.get("tags", ""),
            "body": request.form.get("body", ""),
        })
    else:
        article["tags_text"] = ", ".join(article.get("tags") or [])

    return render_template(
        "knowledge_form.html",
        mode="edit",
        article=article,
        categories=KNOWLEDGE_CATEGORIES,
        result=result,
    )

PARTNERS_DIR = DATA_ROOT / "partner-pools" / "partners"
PARTNER_ASSETS_DIR = DATA_ROOT / "partner-pools" / "assets"
PARTNER_COLORS = {
    "background": "#14281D", "panel": "#20382A", "accent": "#57D68D",
    "text": "#F5FBF4", "secondary": "#275941",
}
_PORTAL_PULL_LOCK = threading.Lock()


@app.route("/portal-sync/pull", methods=["POST"])
def portal_sync_pull():
    """Catch up while Admin is open; no online event is discarded on network failure."""
    from portal_sync import pull_events, SyncError
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return jsonify(error="Portal connection is not configured"), 409
    if not _PORTAL_PULL_LOCK.acquire(blocking=False):
        return jsonify(ok=True, already_running=True)
    try:
        total = 0
        for _ in range(10):
            count, cursor = pull_events(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                        secret, DATA_ROOT / "partner-pools" / "portal-inbox")
            total += count
            if count < 100:
                break
        return jsonify(ok=True, received=total, cursor=cursor)
    except SyncError as exc:
        return jsonify(error=str(exc)), 503
    finally:
        _PORTAL_PULL_LOCK.release()


def _partner_id(value):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value or ""))


def _read_partner(partner_id):
    if not _partner_id(partner_id):
        return None
    record = load_json(PARTNERS_DIR / (partner_id + ".json"), None)
    if not isinstance(record, dict) or record.get("id") != partner_id or record.get("schema") != "tpf_partner_v1":
        return None
    return record


def _all_partners():
    records = [item["data"] for item in load_json_files(PARTNERS_DIR)
               if isinstance(item.get("data"), dict) and item["data"].get("schema") == "tpf_partner_v1"]
    return sorted(records, key=lambda record: record.get("name", "").casefold())


def _write_partner(record):
    PARTNERS_DIR.mkdir(parents=True, exist_ok=True)
    destination = PARTNERS_DIR / (record["id"] + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".partner-", dir=PARTNERS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _partner_pool(pool_id):
    if not re.fullmatch(r"pool_[A-Za-z0-9_-]+", pool_id or ""):
        return None
    pool = load_json(DATA_ROOT / "co2-pool" / "pools" / (pool_id + ".json"), None)
    if not isinstance(pool, dict) or pool.get("pool_id") != pool_id:
        return None
    return pool


def _partner_pools_for(partner):
    """Owner in the pool is authoritative; retain old explicitly linked pools."""
    result = {}
    for item in load_json_files(DATA_ROOT / "co2-pool" / "pools"):
        pool = item.get("data")
        if (isinstance(pool, dict) and pool.get("pool_availability") == "dedicated"
                and pool.get("owner_kind") == "partner" and pool.get("owner_partner_id") == partner["id"]
                and pool.get("payment_id") and pool.get("certificates")):
            result[pool["pool_id"]] = pool
    for pool_id in partner.get("pool_ids", []):
        pool = _partner_pool(pool_id)
        if pool and not pool.get("owner_kind") and pool.get("payment_id") and pool.get("certificates"):
            result[pool_id] = pool
    return sorted(result.values(), key=lambda pool: (pool.get("created_at", ""), pool["pool_id"]))


def _portal_connections_for(partner_id, pools):
    """Only locally confirmed request-to-pool links enter a publication."""
    result = []
    directory = DATA_ROOT / "partner-pools" / "portal-connections"
    for pool in pools:
        item = load_json(directory / (pool["pool_id"] + ".json"), None)
        if item is not None:
            if item.get("partnerId") != partner_id or item.get("poolId") != pool["pool_id"]:
                raise ValueError("A saved request connection does not match this pool owner.")
            result.append({key: item[key] for key in ("requestId", "offerId", "choiceKey", "poolId")})
    return result


def _partner_form_record(form, existing=None):
    name = (form.get("name") or "").strip()[:120]
    section_title = (form.get("section_title") or "").strip()[:120]
    if not name or not section_title:
        raise ValueError("Partner name and page title are required.")
    record = dict(existing) if existing else {
        "schema": "tpf_partner_v1", "id": "", "created_at": now_iso(),
        "offer_ids": [], "pool_ids": [], "logo_file": "", "status": "draft",
        "history": [],
    }
    if not existing:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        if not _partner_id(slug):
            raise ValueError("Enter a partner name containing letters or numbers.")
        if _read_partner(slug):
            raise ValueError("This partner already exists; open it to edit.")
        record["id"] = slug
    record.update(name=name, section_title=section_title,
                  tagline=(form.get("tagline") or "").strip()[:240],
                  intro=(form.get("intro") or "").strip()[:1500],
                  internal_notes=(form.get("internal_notes") or "").strip()[:2000],
                  updated_at=now_iso())
    colors = {}
    for key, default in PARTNER_COLORS.items():
        value = (form.get("color_" + key) or default).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Use six-digit colour codes such as #43DCFF.")
        colors[key] = value.upper()
    record["colors"] = colors
    return record


@app.route("/partners")
def partners_home():
    partners = _all_partners()
    for partner in partners:
        partner["linked_pool_count"] = len(_partner_pools_for(partner))
    return render_template("partners.html", partners=partners)


def _read_partner_logo_upload(upload):
    if not upload or not upload.filename:
        return None
    content = upload.stream.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("Logo exceeds 2 MB.")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        extension = "webp"
    else:
        raise ValueError("Use a PNG, JPEG or WebP logo.")
    return content, extension


def _store_partner_logo(partner_id, uploaded):
    content, extension = uploaded
    PARTNER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    destination = PARTNER_ASSETS_DIR / (partner_id + "." + extension)
    fd, temporary = tempfile.mkstemp(prefix=".logo-", dir=PARTNER_ASSETS_DIR)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination.name


@app.route("/partners/new", methods=["GET", "POST"])
def partner_new():
    if request.method == "POST":
        try:
            record = _partner_form_record(request.form)
            uploaded_logo = _read_partner_logo_upload(request.files.get("logo"))
        except ValueError as exc:
            return render_template("partner_form.html", partner=request.form, colors=PARTNER_COLORS,
                                   error=str(exc), is_new=True), 400
        if uploaded_logo:
            record["logo_file"] = _store_partner_logo(record["id"], uploaded_logo)
        _write_partner(record)
        return redirect(url_for("partner_detail", partner_id=record["id"]))
    return render_template("partner_form.html", partner={}, colors=PARTNER_COLORS, error=None, is_new=True)


@app.route("/partners/<partner_id>")
def partner_detail(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    offers = [_read_partner_offer(offer_id) for offer_id in partner.get("offer_ids", [])]
    pools = _partner_pools_for(partner)
    linked_offers = [offer for offer in offers if offer]
    linked_pools = pools
    used_offers = {offer_id for item in _all_partners() if item["id"] != partner_id
                   for offer_id in item.get("offer_ids", [])}
    used_pools = {pool_id for item in _all_partners() if item["id"] != partner_id
                  for pool_id in item.get("pool_ids", [])}
    available_offers = [item["data"] for item in load_json_files(PARTNER_OFFERS_DIR)
                        if isinstance(item.get("data"), dict)
                        and item["data"].get("schema") == "tpf_partner_offer_v1"
                        and item["data"].get("status") == "accepted"
                        and item["data"].get("id") not in used_offers
                        and item["data"].get("id") not in partner.get("offer_ids", [])]
    # Ownership is chosen at pool creation. Old unassigned pools are assigned
    # once on their own detail pages rather than offered in every partner form.
    available_pools = []
    sync_file = DATA_ROOT / "partner-pools" / "portal-sync" / (partner_id + ".json")
    sync_state = load_json(sync_file, {}) or {}
    return render_template("partner_detail.html", partner=partner, portal_public_url=os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org").rstrip("/") + "/p/" + partner_id + "/", offers=linked_offers,
                           pools=linked_pools, available_offers=available_offers,
                           available_pools=available_pools, sync_state=sync_state,
                           portal_ready=bool(os.getenv("TPF_OPS_SYNC_SECRET")))


@app.route("/partners/<partner_id>/workspace", methods=["GET"])
def partner_workspace_readonly(partner_id):
    """Read current online data. Never mint a partner session or send mutations."""
    from portal_sync import signed_request, SyncError
    if _read_partner(partner_id) is None:
        return "Partner not found", 404
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return "Portal connection is not configured. No workspace data was loaded.", 409
    origin = os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org").rstrip("/")
    try:
        data = signed_request(origin, secret, "GET", "/api/ops/workspace?partnerId=" + quote(partner_id, safe=""))
        if not data.get("readOnly") or data.get("profile", {}).get("id") != partner_id:
            raise SyncError("Invalid online workspace response")
    except SyncError:
        return "Online workspace could not be loaded. No cached or local balances are shown. Retry after checking the Portal connection.", 503
    response = app.make_response(render_template("partner_workspace_readonly.html",
        workspace_data={**data, "portalOrigin": origin}, portal_origin=origin, retrieved_at=data.get("retrievedAt", ""),
        admin_partner_url=url_for("partner_detail", partner_id=partner_id)))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

@app.route("/partners/<partner_id>/portal-sync", methods=["POST"])
def partner_portal_sync(partner_id):
    """Explicit local action; never publishes a pool without Admin export proof."""
    from portal_sync import publish_partner, SyncError
    from partner_public_export import make_export, ExportNotReady
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return "Portal connection is not configured.", 409
    pools = _partner_pools_for(partner)
    try:
        connections = _portal_connections_for(partner_id, pools)
    except ValueError as exc:
        return "Nothing was published: " + str(exc), 409
    # Publishing branding needs no planting. Pool export remains proof-checked.
    activate = True
    to_send = dict(partner)
    if activate:
        to_send["status"] = "active"
    try:
        result = publish_partner(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                 secret, to_send, pools, PARTNER_ASSETS_DIR, make_export,
                                 connections=connections)
    except (SyncError, ExportNotReady, ValueError) as exc:
        return "Nothing was published: " + str(exc), 409
    state = {"synced_at": now_iso(), "revision": result.get("revision"),
             "published_pools": result.get("publishedPools", 0)}
    if result.get("invitationUrl"):
        state["invitation_url"] = result["invitationUrl"]
    if activate and partner.get("status") != "active":
        partner["status"] = "active"
        partner["updated_at"] = now_iso()
        _write_partner(partner)
    state_file = DATA_ROOT / "partner-pools" / "portal-sync" / (partner_id + ".json")
    save_json(state_file, state)
    return redirect(url_for("partner_detail", partner_id=partner_id))


@app.route("/partners/<partner_id>/new-invitation", methods=["POST"])
def partner_new_invitation(partner_id):
    from portal_sync import new_invitation, SyncError
    if not _read_partner(partner_id):
        return "Partner not found", 404
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return "Portal connection is not configured.", 409
    try:
        result = new_invitation(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                secret, partner_id)
    except SyncError as exc:
        return "Invitation was not created: " + str(exc), 409
    state_file = DATA_ROOT / "partner-pools" / "portal-sync" / (partner_id + ".json")
    state = load_json(state_file, {}) or {}
    state["invitation_url"] = result["invitationUrl"]
    state["invitation_created_at"] = now_iso()
    save_json(state_file, state)
    return redirect(url_for("partner_detail", partner_id=partner_id))


@app.route("/partners/portal-inbox", methods=["GET", "POST"])
def partner_portal_inbox():
    from portal_sync import pull_events, SyncError
    inbox = DATA_ROOT / "partner-pools" / "portal-inbox"
    error = None
    if request.method == "POST":
        secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
        if len(secret) < 32:
            error = "Portal connection is not configured."
        else:
            try:
                pull_events(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                            secret, inbox)
            except SyncError as exc:
                error = str(exc)
    events = [item["data"] for item in load_json_files(inbox)
              if isinstance(item.get("data"), dict) and item["data"].get("event_type")]
    events.sort(key=lambda item: int(item.get("id", 0)), reverse=True)
    ready_offers = [item["data"] for item in load_json_files(PARTNER_OFFERS_DIR)
                    if isinstance(item.get("data"), dict)
                    and item["data"].get("schema") == "tpf_partner_offer_v1"
                    and item["data"].get("status") == "ready"]
    connections = [item["data"] for item in load_json_files(
        DATA_ROOT / "partner-pools" / "portal-connections")
        if isinstance(item.get("data"), dict)]
    connected_by_request = {item.get("requestId"): item.get("poolId") for item in connections}
    used_pools = {item.get("poolId") for item in connections}
    connectable = {}
    for event in events:
        if event.get("event_type") != "offer.selected":
            continue
        partner = _read_partner(event.get("partner_id"))
        if not partner:
            continue
        basis = event.get("selected_basis")
        units_key = "quantity" if basis == "trees" else "total_co2_kg"
        promised_key = "selected_trees" if basis == "trees" else "selected_co2_kg"
        try:
            promised = Decimal(str(event.get(promised_key)))
            available = [pool for pool in _partner_pools_for(partner)
                         if pool.get("allocation_basis") == basis
                         and pool.get("owner_kind") == "partner"
                         and pool.get("owner_partner_id") == partner["id"]
                         and pool["pool_id"] not in used_pools
                         and Decimal(str(pool.get(units_key) or 0)) >= promised]
        except (InvalidOperation, TypeError):
            available = []
        connectable[str(event["id"])] = available
    online_requests = {}
    try:
        from portal_sync import signed_request
        for partner_id in {item.get("partner_id") for item in events if item.get("partner_id")}:
            online = signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                    os.getenv("TPF_OPS_SYNC_SECRET", ""), "GET",
                                    "/api/ops/workspace?partnerId=" + partner_id)
            online_requests.update({item["id"]: item for item in online.get("requests", [])})
    except SyncError as exc:
        error = "Current order status unavailable: " + str(exc)
    access_requests = []
    access_error = None
    if os.getenv("TPF_OPS_SYNC_SECRET"):
        try:
            from portal_sync import signed_request
            access_requests = signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                os.getenv("TPF_OPS_SYNC_SECRET", ""), "GET", "/api/ops/access-requests").get("requests", [])
        except SyncError as exc:
            access_error = "Access requests unavailable: " + str(exc)
    recent = load_json(wallet_transactions_file(), {}) or {}
    payment_candidates = [tx for tx in recent.get("transactions", [])
                          if tx.get("network") == "mainnet" and tx.get("direction") == "incoming"
                          and tx.get("blockchain_verified") and tx.get("asset_type") == "native"
                          and not load_wallet_classification(tx.get("tx_hash"))]
    selected_payment_tx = request.args.get("payment_tx", "").lower()
    payment_audits = {}
    for item in load_json_files(DATA_ROOT / "partner-pools" / "payment-matches"):
        audit = item.get("data")
        if isinstance(audit, dict):
            payment_audits[audit.get("request_id")] = audit
    return render_template("partner_portal_inbox.html", payment_candidates=payment_candidates, selected_payment_tx=selected_payment_tx, payment_audits=payment_audits, access_requests=access_requests, access_error=access_error, online_requests=online_requests, events=events[:100], error=error,
                           ready_offers=ready_offers, connectable=connectable,
                           connected_by_request=connected_by_request,
                           portal_ready=bool(os.getenv("TPF_OPS_SYNC_SECRET")))


@app.route("/partners/access-requests/<request_id>/handled", methods=["POST"])
def partner_access_handled(request_id):
    from portal_sync import signed_request, SyncError
    if not re.fullmatch(r"[a-f0-9-]{36}", request_id):
        return "Request not found", 404
    if request.form.get("confirm_handled") != "yes":
        return "Confirm you have handled this access request.", 400
    try:
        signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                       os.getenv("TPF_OPS_SYNC_SECRET", ""), "POST", "/api/ops/handle-access", {"id": request_id})
    except SyncError as exc:
        return "Access request was not marked handled: " + str(exc), 502
    return redirect(url_for("partner_portal_inbox"))


@app.route("/partners/<partner_id>/requests/<request_id>/order", methods=["POST"])
def partner_portal_order(partner_id, request_id):
    from portal_sync import signed_request, SyncError
    if not _read_partner(partner_id) or not re.fullmatch(r"[a-f0-9-]{36}", request_id):
        return "Partner request not found", 404
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return "Cross-site payment actions are not allowed.", 403
    action = request.form.get("action")
    if action not in ("cancel", "confirm-payment"):
        return "Invalid action", 400
    if request.form.get("confirm_action") != "yes":
        return "Confirm the reviewed action first.", 400
    body = {"partnerId": partner_id, "requestId": request_id, "action": action}
    if action == "cancel":
        try:
            signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                           os.getenv("TPF_OPS_SYNC_SECRET", ""), "POST", "/api/ops/order", body)
        except SyncError as exc:
            return "Order was not updated: " + str(exc), 409
        return redirect(url_for("partner_portal_inbox"))
    if ACTIVE_ENV != "mainnet":
        return "Partner payment confirmation is available in mainnet only.", 409
    if request.form.get("confirm_sender") != "yes":
        return "Confirm that the sender belongs to the partner and this payment is for this selected offer.", 400
    from partner_payment import verify_payment, check_match, payment_lock, write_audit, FUND_ID
    tx_hash = request.form.get("payment_reference", "").strip().lower()
    method = request.form.get("match_method", "")
    note = request.form.get("match_note", "").strip()
    root = DATA_ROOT / "partner-pools" / "payment-matches"
    try:
        with payment_lock(root):
            audit_path = root / (request_id + ".json")
            previous = load_json(audit_path, {}) or {}
            if previous and previous.get("tx_hash") != tx_hash:
                raise ValueError("This order already has payment evidence. Review it before replacing a transaction.")
            for item in load_json_files(root):
                audit = item.get("data", {})
                if audit.get("tx_hash") == tx_hash and audit.get("request_id") != request_id:
                    raise ValueError("This transaction is already reserved for another partner order")
            classification = load_wallet_classification(tx_hash)
            if classification and classification.get("partner_request_id") != request_id:
                raise ValueError("This payment is already classified. Reconcile its existing records before matching it.")
            for entry in load_fund_ledger().get("entries", []):
                if (entry.get("tx_hash", "").lower() == tx_hash
                        and entry.get("partner_request_id") != request_id):
                    raise ValueError("This transaction already has a fund entry. Reconcile it before matching.")
            if tx_hash in donation_files_with_tx_hash():
                raise ValueError("This payment already appears in the regular planting workflow. Reconcile before matching.")
            evidence = verify_payment(tx_hash, load_wallet_sources(), requests.get)
            events = [item.get("data", {}) for item in load_json_files(DATA_ROOT / "partner-pools" / "portal-inbox")]
            selected = [event for event in events if event.get("event_type") == "offer.selected"
                        and event.get("partner_id") == partner_id and event.get("offer_request_id") == request_id]
            if len(selected) != 1:
                raise ValueError("Fetch the selected offer into the local inbox first")
            check_match(evidence, partner_id, request_id, selected[0].get("selected_price_pi"), method, note)
            audit = dict(evidence, schema="tpf_partner_payment_match_v1", partner_id=partner_id,
                         request_id=request_id, match_method=method, match_note=note,
                         sender_confirmed=True, checked_at=now_iso(), status="prepared")
            # Save evidence before changing the online order. Retrying the same hash
            # resumes safely if network or local bookkeeping failed midway.
            if previous.get("status") in ("online_confirmed", "complete"):
                audit = previous
            write_audit(audit_path, audit)
            body.update(paymentReference=tx_hash, amountPi=evidence["amount_pi"], confirmVerified=True)
            result = signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                    os.getenv("TPF_OPS_SYNC_SECRET", ""), "POST", "/api/ops/order", body)
            if result.get("status") not in ("planting_pending", "connected"):
                raise ValueError("Unexpected online confirmation response; payment audit retained for review")
            audit["status"] = "online_confirmed"
            write_audit(audit_path, audit)
            fund = get_fund(FUND_ID)
            if not fund or fund.get("workflow") != "record_only" or fund.get("status") != "active":
                raise ValueError("Partner payment fund must be active with Record only workflow; retry after correcting it")
            partner = _read_partner(partner_id)
            display_name = partner.get("name") or partner_id
            entry = dict(evidence, direction="incoming", fund_id=FUND_ID,
                         fund_name_snapshot=fund["name"], fund_type_snapshot=fund["fund_type"],
                         wallet_address=evidence["from_address"], display_name=display_name,
                         note=note, partner_id=partner_id, partner_request_id=request_id,
                         source="verified_partner_order")
            add_fund_ledger_entry(entry)
            save_wallet_classification(tx_hash, dict(entry, classification="fund", fund_name=fund["name"],
                fund_workflow="record_only", status="fund_recorded", confirmed_at=now_iso()))
            audit["status"] = "complete"
            write_audit(audit_path, audit)
    except (ValueError, SyncError, requests.RequestException, OSError) as exc:
        return "Payment matching did not finish: " + str(exc) + ". Review the local payment audit and retry the same transaction if needed.", 409
    return redirect(url_for("partner_portal_inbox"))


@app.route("/partners/<partner_id>/requests/<request_id>/connect-pool", methods=["POST"])
def partner_portal_connect_pool(partner_id, request_id):
    """Connect a selected request only after payment and planting proof exist locally."""
    from portal_sync import publish_partner, SyncError
    from partner_public_export import make_export, ExportNotReady
    partner = _read_partner(partner_id)
    if not partner or not re.fullmatch(r"[a-f0-9-]{36}", request_id):
        return "Partner request not found", 404
    if request.form.get("confirm_verified") != "yes":
        return "Confirm the verified payment and planting before connecting.", 400
    payment_audit = load_json(DATA_ROOT / "partner-pools" / "payment-matches" / (request_id + ".json"), {}) or {}
    if payment_audit and payment_audit.get("status") != "complete":
        return "Finish the verified payment bookkeeping before connecting this pool. Resume the same payment in online activity.", 409
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return "Portal connection is not configured.", 409
    events = [item["data"] for item in load_json_files(
        DATA_ROOT / "partner-pools" / "portal-inbox") if isinstance(item.get("data"), dict)]
    selected = [item for item in events if item.get("event_type") == "offer.selected"
                and item.get("partner_id") == partner_id
                and item.get("offer_request_id") == request_id]
    if len(selected) != 1:
        return "Fetch the selected offer into the local inbox first.", 409
    event = selected[0]
    try:
        from portal_sync import signed_request
        online = signed_request(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                secret, "GET", "/api/ops/workspace?partnerId=" + partner_id)
        order = next((item for item in online.get("requests", []) if item["id"] == request_id), None)
        if not order or order.get("status") != "planting_pending" or not order.get("payment_reference"):
            return "Record the verified payment before connecting this request.", 409
    except SyncError as exc:
        return "Could not verify online payment status: " + str(exc), 409
    pool_id = request.form.get("pool_id", "")
    pools = _partner_pools_for(partner)
    pool = next((item for item in pools if item["pool_id"] == pool_id), None)
    basis = event.get("selected_basis")
    if (not pool or basis not in ("trees", "co2") or pool.get("allocation_basis") != basis
            or pool.get("owner_kind") != "partner" or pool.get("owner_partner_id") != partner_id):
        return "Choose a verified pool owned by this partner with the same sharing basis.", 409
    try:
        promised = Decimal(str(event.get("selected_trees" if basis == "trees" else "selected_co2_kg")))
        actual = Decimal(str(pool.get("quantity" if basis == "trees" else "total_co2_kg") or 0))
        if promised <= 0 or actual < promised:
            return "The verified pool contains fewer units than the selected offer promised.", 409
        make_export(partner, [pool], PARTNER_ASSETS_DIR)
        existing = [item["data"] for item in load_json_files(
            DATA_ROOT / "partner-pools" / "portal-connections")
            if isinstance(item.get("data"), dict)]
        if any(item.get("requestId") == request_id or item.get("poolId") == pool_id for item in existing):
            return "This request or pool is already connected. Use Publish / sync to retry.", 409
        link = {"partnerId": partner_id, "requestId": request_id,
                "offerId": event["entity_id"], "choiceKey": event["selected_key"],
                "poolId": pool_id}
        # Persist intent before network access; a timeout can be retried safely.
        save_json(DATA_ROOT / "partner-pools" / "portal-connections" / (pool_id + ".json"), link)
        active = dict(partner, status="active")
        result = publish_partner(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                                 secret, active, pools, PARTNER_ASSETS_DIR, make_export,
                                 connections=_portal_connections_for(partner_id, pools))
    except (InvalidOperation, TypeError, KeyError, SyncError, ExportNotReady, ValueError) as exc:
        return "Connection was not published; retry Publish / sync after review: " + str(exc), 409
    partner["status"] = "active"
    partner["updated_at"] = now_iso()
    _write_partner(partner)
    state_file = DATA_ROOT / "partner-pools" / "portal-sync" / (partner_id + ".json")
    state = load_json(state_file, {}) or {}
    state.update({"synced_at": now_iso(), "revision": result.get("revision"),
                  "published_pools": result.get("publishedPools", 0)})
    if result.get("invitationUrl"):
        state["invitation_url"] = result["invitationUrl"]
    save_json(state_file, state)
    return redirect(url_for("partner_detail", partner_id=partner_id))


@app.route("/partners/<partner_id>/requests/<request_id>/send-offer", methods=["POST"])
def partner_portal_send_offer(partner_id, request_id):
    from portal_sync import send_offer, SyncError
    if not _read_partner(partner_id) or not re.fullmatch(r"[a-f0-9-]{36}", request_id):
        return "Partner request not found", 404
    inbox = DATA_ROOT / "partner-pools" / "portal-inbox"
    received = [entry["data"] for entry in load_json_files(inbox)
                if isinstance(entry.get("data"), dict)
                and entry["data"].get("event_type") == "request.created"
                and entry["data"].get("entity_id") == request_id
                and entry["data"].get("partner_id") == partner_id]
    if not received:
        return "Fetch this partner request into the local inbox first.", 404
    offer = _read_partner_offer(request.form.get("offer_id", ""))
    if not offer or offer.get("status") != "ready" or offer.get("search", {}).get("basis") != received[0].get("request_basis"):
        return "Choose a ready saved offer with the same pool type.", 400
    secret = os.getenv("TPF_OPS_SYNC_SECRET", "")
    if len(secret) < 32:
        return "Portal connection is not configured.", 409
    try:
        result = send_offer(os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org"),
                            secret, partner_id, request_id, offer)
    except SyncError as exc:
        return "Offer was not sent: " + str(exc), 409
    save_json(inbox / ("sent-offer-" + request_id + ".json"),
              {"request_id": request_id, "offer_id": result.get("offerId"), "sent_at": now_iso()})
    return redirect(url_for("partner_portal_inbox"))


@app.route("/partners/<partner_id>/edit", methods=["GET", "POST"])
def partner_edit(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    if request.method == "POST":
        try:
            updated = _partner_form_record(request.form, existing=partner)
            uploaded_logo = _read_partner_logo_upload(request.files.get("logo"))
        except ValueError as exc:
            return render_template("partner_form.html", partner=request.form,
                                   colors=partner.get("colors", PARTNER_COLORS),
                                   error=str(exc), is_new=False), 400
        if uploaded_logo:
            updated["logo_file"] = _store_partner_logo(partner_id, uploaded_logo)
        _write_partner(updated)
        return redirect(url_for("partner_detail", partner_id=partner_id))
    return render_template("partner_form.html", partner=partner,
                           colors=partner.get("colors", PARTNER_COLORS), error=None, is_new=False)


@app.route("/partners/<partner_id>/logo", methods=["POST"])
def partner_logo_upload(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    try:
        uploaded_logo = _read_partner_logo_upload(request.files.get("logo"))
    except ValueError as exc:
        return str(exc), 400
    if not uploaded_logo:
        return "Choose a PNG, JPEG or WebP logo.", 400
    logo_name = _store_partner_logo(partner_id, uploaded_logo)
    partner["logo_file"] = logo_name
    partner["updated_at"] = now_iso()
    _write_partner(partner)
    return redirect(url_for("partner_detail", partner_id=partner_id))


@app.route("/partners/<partner_id>/logo")
def partner_logo(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    name = partner.get("logo_file", "")
    if name not in (partner_id + ".png", partner_id + ".jpg", partner_id + ".webp"):
        return "Logo not found", 404
    from flask import send_file
    path = PARTNER_ASSETS_DIR / name
    if not path.is_file():
        return "Logo not found", 404
    return send_file(path)


@app.route("/partners/<partner_id>/link", methods=["POST"])
def partner_link(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    kind = request.form.get("kind")
    value = request.form.get("id", "")
    if kind == "offer":
        item = _read_partner_offer(value)
        if not item or item.get("status") != "accepted":
            return "Only an accepted saved offer can be linked.", 400
        field = "offer_ids"
    elif kind == "pool":
        return "Assign an old unassigned pool on its pool detail page. New pools get their owner at creation.", 409
    else:
        return "Unknown link type.", 400
    for other in _all_partners():
        if other["id"] != partner_id and value in other.get(field, []):
            return "Already linked to another partner.", 409
    if value not in partner.get(field, []):
        partner.setdefault(field, []).append(value)
        partner.setdefault("history", []).append({
            "at": now_iso(), "action": "linked_" + kind, "id": value,
            "source": "local_tpf_admin",
        })
        partner["updated_at"] = now_iso()
        _write_partner(partner)
    return redirect(url_for("partner_detail", partner_id=partner_id))


@app.route("/partners/<partner_id>/preview")
def partner_preview(partner_id):
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    # Use the public renderer with local branding and actual online ledger data.
    # Local planting data must never pretend to be current online balances.
    from portal_sync import signed_request, SyncError
    origin = os.getenv("TPF_PORTAL_URL", "https://thepioneerforest.org").rstrip("/")
    snapshot = {"pools": [], "records": []}
    warning = ""
    state_file = DATA_ROOT / "partner-pools" / "portal-sync" / (partner_id + ".json")
    if state_file.exists():
        try:
            from urllib.parse import quote
            online = signed_request(origin, os.getenv("TPF_OPS_SYNC_SECRET", ""), "GET",
                "/api/ops/workspace?partnerId=" + quote(partner_id, safe=""))
            if not online.get("readOnly") or online.get("profile", {}).get("id") != partner_id:
                raise SyncError("Invalid workspace response")
            snapshot["pools"] = online.get("pools", [])
            snapshot["records"] = online.get("shares", [])
        except SyncError:
            warning = "Online records could not be loaded. Pool figures are hidden; this preview shows branding only."
    profile = {"id": partner_id, "name": partner["name"],
        "page_title": partner["section_title"], "tagline": partner.get("tagline", ""),
        "introduction": partner.get("intro", ""), "colors": partner.get("colors", PARTNER_COLORS),
        "logo_url": url_for("partner_logo", partner_id=partner_id) if partner.get("logo_file") else None}
    response = app.make_response(render_template("partner_preview.html", partner=partner,
        preview_data={"profile": profile, **snapshot, "portalOrigin": origin}, preview_warning=warning))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/partners/<partner_id>/public-export")
def partner_public_export(partner_id):
    from flask import send_file
    from partner_public_export import ExportNotReady, make_export
    partner = _read_partner(partner_id)
    if partner is None:
        return "Partner not found", 404
    try:
        output = make_export(partner, _partner_pools_for(partner), PARTNER_ASSETS_DIR)
    except ExportNotReady as exc:
        return str(exc), 409
    return send_file(output, mimetype="application/zip", as_attachment=True,
                     download_name=partner_id + "-public-setup-preview.zip")


if __name__ == "__main__":
    app.run(debug=True)
