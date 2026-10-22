"""Saved-state-only 8 AM MTD completed-sales heartbeat.

The scheduled form emits only after that day's verified 8 AM primary sales check.
Use MTD_HEARTBEAT_SAMPLE=1 solely for an explicitly requested layout preview.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STATE = Path(r"__HERMES_HOME__/price-watches/mcfarlane-dc-sales.json")
ALIASES = STATE.with_name("mcfarlane-wallet-aliases.json")
EASTERN = ZoneInfo("America/New_York")
sys.path.insert(0, str(STATE.parent))
from mcfarlane_wallet_aliases import alias_for_wallet


def parsed(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def usd_text(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "USD unavailable"


def buyer_text(sale, aliases):
    wallet = str(sale.get("buyer_wallet") or sale.get("buyer") or "").split(":")[-1].lower()
    current = alias_for_wallet(wallet, aliases)
    if current:
        return str(current)
    if sale.get("buyer_name_tag"):
        return str(sale["buyer_name_tag"])
    if sale.get("buyer_display"):
        return str(sale["buyer_display"])
    if wallet:
        return "..." + wallet[-9:]
    return "Buyer not recorded"


state = json.loads(STATE.read_text(encoding="utf-8"))
aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
if os.environ.get("MTD_HEARTBEAT_SAMPLE") != "1":
    checked = parsed(state.get("last_successful_check_at"))
    now = datetime.now(EASTERN)
    if not checked or checked.astimezone(EASTERN).date() != now.date() or checked.astimezone(EASTERN).hour != 8:
        print("[SILENT]")
        raise SystemExit(0)
collections = {item.get("id"): item for item in state.get("collections") or []}
sales = sorted((item for item in state.get("recent_sales") or [] if isinstance(item, dict)), key=lambda item: item.get("date") or "", reverse=True)[:20]
lines = ["**MTD Sales Alert — 8 AM heartbeat (last 20)**"]
for sale in sales:
    collection = collections.get(sale.get("collection"), {})
    name = collection.get("display_name") or sale.get("collection") or "Unknown collection"
    price = sale.get("price") or (sale.get("payment") or {}).get("value") or "Unknown"
    sold = str(sale.get("date") or "").replace("T", " ")[:16] or "time not recorded"
    lines.append(f"• {sold} - {sale.get('rarity') or 'Unknown'} - {price} POL ({usd_text(sale.get('usd_amount'))}) - {name} - Buy: {buyer_text(sale, aliases)}")
if not sales:
    lines.append("• No saved completed sales.")
sys.stdout.write("\n".join(lines) + "\n")
