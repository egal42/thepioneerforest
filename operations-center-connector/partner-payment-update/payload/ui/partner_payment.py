"""Verified mainnet payment matching; never invent or edit a blockchain memo."""
import json
import os
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

FUND_ID = "partner_pool_payments"


def pi_amount(value):
    if not re.fullmatch(r"\d+(?:\.\d{1,7})?", str(value)):
        raise ValueError("Invalid Pi amount")
    amount = Decimal(str(value))
    if amount <= 0:
        raise ValueError("Pi amount must be positive")
    return amount


def verify_payment(tx_hash, sources, get):
    if not re.fullmatch(r"[a-f0-9]{64}", tx_hash or ""):
        raise ValueError("Choose a valid transaction hash")
    wallets = {s.get("wallet_address") for s in sources
               if s.get("enabled", True) and s.get("network") == "mainnet"}
    root = "https://api.mainnet.minepi.com/transactions/" + tx_hash
    response = get(root, timeout=20)
    response.raise_for_status()
    tx = response.json()
    if tx.get("hash") != tx_hash or tx.get("successful") is not True:
        raise ValueError("The mainnet transaction is not successful")
    response = get(root + "/operations?limit=200", timeout=20)
    response.raise_for_status()
    operations = response.json().get("_embedded", {}).get("records", [])
    # Hash-level order uniqueness cannot represent separate payments in one TX.
    # Fail closed for batches rather than selecting an arbitrary operation.
    if len(operations) != tx.get("operation_count"):
        raise ValueError("Could not verify every transaction operation")
    payments = [op for op in operations if op.get("type") == "payment"
                and op.get("asset_type") == "native" and op.get("to") in wallets]
    if len(payments) != 1:
        raise ValueError("Expected exactly one native Pi payment to a configured TPF mainnet wallet")
    op = payments[0]
    if op.get("transaction_hash") != tx_hash or not op.get("from") or not op.get("id"):
        raise ValueError("Incomplete blockchain payment evidence")
    amount = pi_amount(op.get("amount"))
    return {"tx_hash": tx_hash, "operation_id": str(op["id"]),
            "amount_pi": str(amount), "from_address": op["from"],
            "to_address": op["to"], "created_at_chain": tx.get("created_at"),
            "memo_type": tx.get("memo_type", "none"),
            "blockchain_memo": str(tx.get("memo") or ""), "network": "mainnet"}


def check_match(evidence, partner_id, request_id, selected_amount, method, note):
    if pi_amount(evidence["amount_pi"]) != pi_amount(selected_amount):
        raise ValueError("The received Pi amount does not equal the selected offer price")
    expected = partner_id.replace("-", "")[:6].upper() + "-" + request_id[-12:].upper()
    if method == "memo":
        if evidence.get("memo_type") != "text" or evidence.get("blockchain_memo") != expected:
            raise ValueError("The on-chain text memo does not match this request; use manual matching with evidence")
    elif method == "manual":
        if len(note.strip()) < 16 or len(note) > 1000:
            raise ValueError("Explain the manual match (16–1000 characters), including how the partner confirmed it")
    else:
        raise ValueError("Choose memo matching or manual matching")


def write_audit(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


@contextmanager
def payment_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".payment-confirmation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Another payment confirmation is running, or a previous run stopped unexpectedly. Review before retrying.")
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()
