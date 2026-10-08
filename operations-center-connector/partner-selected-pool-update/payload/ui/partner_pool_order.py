"""Resolve the paid offer by IDs, never by amount or catalogue position."""
import hashlib
import json
from decimal import Decimal


def resolve_choice(event, offer, audit, order):
    if (not offer or offer.get("id") != event.get("entity_id")
            or offer.get("schema") != "tpf_partner_offer_v1"):
        raise ValueError("The original saved offer is missing. Restore it before preparing planting.")
    if (audit.get("status") != "complete" or order.get("status") != "planting_pending"
            or not order.get("payment_reference") or order["payment_reference"] != audit.get("tx_hash")
            or audit.get("partner_id") != event.get("partner_id")
            or audit.get("request_id") != event.get("offer_request_id")):
        raise ValueError("The order needs a completed verified payment before planting")
    choices = [c for c in offer.get("choices", []) if c.get("key") == event.get("selected_key")]
    if len(choices) != 1:
        raise ValueError("The exact selected option is missing or ambiguous")
    choice = choices[0]
    if choice["key"] != f'{choice.get("project_id")}:{choice.get("species_id")}':
        raise ValueError("The selected option IDs are inconsistent")
    for local, remote in [("partner_price_pi", "selected_price_pi"), ("trees", "selected_trees"), ("co2_kg", "selected_co2_kg")]:
        if Decimal(str(choice.get(local))) != Decimal(str(event.get(remote))):
            raise ValueError("The saved option differs from the partner's recorded selection")
    if Decimal(str(audit["amount_pi"])) != Decimal(str(choice["partner_price_pi"])):
        raise ValueError("The paid amount differs from this selected option")
    basis = event.get("selected_basis")
    if basis not in ("trees", "co2") or offer.get("search", {}).get("basis") != basis:
        raise ValueError("The selected sharing basis is inconsistent")
    trees = Decimal(str(choice["trees"]))
    if trees <= 0 or trees != trees.to_integral_value() or Decimal(str(choice["co2_kg"])) <= 0:
        raise ValueError("The selected offer has invalid planting quantities")
    return dict(choice)


def selected_catalog_option(choice, catalog):
    matches = [(p, s) for p in catalog.get("projects", []) for s in p.get("species", [])
               if str(p.get("project_id")) == str(choice["project_id"])
               and str(s.get("id")) == str(choice["species_id"])]
    if len(matches) != 1:
        raise ValueError("The selected project/species is unavailable in the catalogue; no substitution is allowed")
    project, species = matches[0]
    quantity = int(choice["trees"])
    if Decimal(str(species.get("stock", 0))) < quantity:
        raise ValueError("Insufficient stock for the exact selected tree quantity")
    price = Decimal(str(species.get("price", 0)))
    co2 = Decimal(str(species.get("life_time_CO2", 0)))
    cost = (price * quantity).quantize(Decimal("0.01"))
    if price <= 0 or co2 * quantity != Decimal(str(choice["co2_kg"])):
        raise ValueError("The catalogue CO₂ estimate differs from the agreed offer; review before planting")
    if cost != Decimal(str(choice["planting_cost_eur"])):
        raise ValueError("The planting cost has changed since the offer; review before planting")
    return {"project_id": choice["project_id"], "species_id": choice["species_id"],
            "project_name": choice["project"], "species_name": choice["species"],
            "quantity_needed": quantity, "total_co2": float(co2 * quantity),
            "total_cost": float(cost), "co2_per_eur": float(co2 / price),
            "option_status": "partner_offer", "status_label": "Paid partner offer",
            "status_reason": "Exact individually agreed partner option; general contribution minimum does not apply."}


def selection_revision(event, choice, audit):
    value = {"partner": event["partner_id"], "request": event["offer_request_id"],
             "offer": event["entity_id"], "basis": event["selected_basis"],
             "choice": choice, "payment": audit["tx_hash"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
