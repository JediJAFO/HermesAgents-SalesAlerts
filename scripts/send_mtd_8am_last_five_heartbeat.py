"""Saved-state-only 8 AM MTD completed-sales heartbeat.

The scheduled form emits only after that day's verified 8 AM primary sales check.
Use MTD_HEARTBEAT_SAMPLE=1 solely for an explicitly requested layout preview;
sample rendering does not refresh the production analytics artifact.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STATE = Path(r"__HERMES_HOME__/price-watches/mcfarlane-dc-sales.json")
ALIASES = STATE.with_name("mcfarlane-wallet-aliases.json")
ANALYTICS = STATE.with_name("mtd-sales-analytics.json")
ANALYTICS_MODULE = STATE.with_name("mtd_sales_analytics.py")
EASTERN = ZoneInfo("America/New_York")
RECAP_LIMIT = 30
DISCORD_CHUNK_LIMIT = 1900
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


def load_analytics(module_path):
    spec = importlib.util.spec_from_file_location("mtd_sales_heartbeat_analytics", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("analytics module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(state, aliases):
    collections = {item.get("id"): item for item in state.get("collections") or []}
    sales = sorted((item for item in state.get("recent_sales") or [] if isinstance(item, dict)),
                   key=lambda item: (item.get("date") or "", item.get("activity_id") or item.get("id") or ""), reverse=True)[:RECAP_LIMIT]
    lines = ["**MTD Sales Alert — 8 AM heartbeat (last 30)**"]
    for sale in sales:
        collection = collections.get(sale.get("collection"), {})
        name = collection.get("display_name") or sale.get("collection") or "Unknown collection"
        price = sale.get("price") or (sale.get("payment") or {}).get("value") or "Unknown"
        sold = str(sale.get("date") or "").replace("T", " ")[:16] or "time not recorded"
        lines.append(f"• {sold} - {sale.get('rarity') or 'Unknown'} - {price} POL ({usd_text(sale.get('usd_amount'))}) - {name} - Buy: {buyer_text(sale, aliases)}")
    if not sales:
        lines.append("• No saved completed sales.")
    return "\n".join(lines) + "\n"


def render_chunks(state, aliases, limit=DISCORD_CHUNK_LIMIT):
    """Split only on transaction boundaries; never silently drop saved rows."""
    lines = render(state, aliases).rstrip("\n").split("\n")
    chunks = []
    current = []
    for line in lines:
        candidate = "\n".join([*current, line])
        if current and len(candidate) > limit:
            chunks.append("\n".join(current) + "\n")
            current = ["**MTD Sales Alert — 8 AM heartbeat (last 30, continued)**", line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current) + "\n")
    return chunks


def main(*, state_path=STATE, aliases_path=ALIASES, analytics_path=ANALYTICS, now=None, sample=None):
    state_path = Path(state_path); aliases_path = Path(aliases_path); analytics_path = Path(analytics_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    sample = os.environ.get("MTD_HEARTBEAT_SAMPLE") == "1" if sample is None else sample
    current = now or datetime.now(EASTERN)
    if not sample:
        checked = parsed(state.get("last_successful_check_at"))
        if not checked or checked.astimezone(EASTERN).date() != current.date() or checked.astimezone(EASTERN).hour != 8:
            print("[SILENT]")
            return 0
    output = "\n--- MTD SALES HEARTBEAT CHUNK ---\n".join(render_chunks(state, aliases))
    if not sample:
        analytics = load_analytics(ANALYTICS_MODULE)
        analytics.refresh_analytics(state_path, aliases_path, analytics_path)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
