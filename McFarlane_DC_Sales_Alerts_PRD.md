# Product Requirements Document — MTD Completed-Sale Alerts

**Compatibility filename:** `McFarlane_DC_Sales_Alerts_PRD.md`  
**Review date:** 2026-10-22  
**Status:** Active all-category monitor; the filename is legacy.  
**Verification boundary:** Reviewed current local source, private-state aggregates, `jobs.json`, and execution records. No marketplace/API request, notification, DOCX generation, or backup push was performed.

## 1. Purpose and current scope

Detect newly completed marketplace sales for the approved private McFarlane Toys Digital allowlist. Current state contains **128 collections** across eight categories: **DC 75, Spawn 22, UFC 12, Universal 7, McFarlane Dragons 7, Walking Dead 2, McFarlane Digital 2, and BRZRKR 1**. Counts were computed from current state; exact contracts and onboarding baselines remain private.

This monitor is independent of the rarity-listing watches. It consumes completed activity, not active listings, and does not purchase or bid.

## 2. Collection implementation

The primary wrapper runs the current completed-sales collector. It submits one Rarible Activities search for Polygon `SELL` activity, newest first, with page size **1,000**, the exact allowlist, and a saved baseline date.

A record is accepted only when it is a non-reverted `SELL`, belongs to the allowlist, is newer than applicable collection/category onboarding baselines, and is not already in the saved activity-ID ledger. The implementation does not independently accept a top-level `ACCEPT_BID` activity unless the provider exposes the completion as `SELL`.

For each new sale the collector attempts collection and item metadata enrichment, including item name and exact `Rarity` attribute. Metadata failure degrades display fields rather than invalidating an otherwise accepted sale. Buyer and seller labels use the canonical private alias database where possible and otherwise show masked suffixes.

Historical USD uses provider sale-time USD fields first, then a previously cached date-keyed POL/USD rate. Missing historical valuation remains unavailable; old sales must not be repriced using current spot.

## 3. Authoritative schedules

Schedules were read from current `jobs.json`. Relevant jobs have no explicit timezone field; intended local interpretation is America/New_York.

| Function | Current schedule / state |
| --- | --- |
| Primary completed-sales collection | 00:00, 08:00, 12:00, 16:00, 20:00 daily |
| Saved last-20 heartbeat | 08:05 daily |
| HTTP-400 retry poll | Every 5 minutes |
| Collection metadata enrichment | Every 5 minutes |
| WhatsApp sales consumer | Configured for minute 15 after primary hours but **disabled** |
| Daily source backup attempt | 23:50 |

The 08:05 heartbeat is saved-state-only and emits only when `last_successful_check_at` is from the current date’s 08:00 hour. It has no durable owed-heartbeat/catch-up mechanism.

## 4. Output contract

- A successful no-sale primary prints an explicit update-complete status.
- New sales are aggregated with category, collection, item, rarity, amount, captured USD when available, masked parties, and truncated sale time.
- The current renderer labels the amount as POL without independently validating the payment asset. Quantity is retained but omitted from the alert line.
- The heartbeat renders the **20** newest saved recap rows, not a live “last 20” query.
- The disabled WhatsApp script reads pending saved state only; it makes no marketplace request.

## 5. Retention and correctness limits

Current bounded retention is:

- `recent_sales`: newest **20** normalized sales.
- `seen_activity_ids`: newest **2,000** IDs.
- One pending WhatsApp batch object, overwritten by a later new batch.

The API request is a single page and does not follow the returned cursor. Therefore the monitor does not prove exhaustive coverage when more than 1,000 qualifying records fall in the queried range. The saved cursor field is observational only. The baseline watermark is not advanced to the newest processed sale; dedupe relies on onboarding baselines plus the bounded ID ledger.

Primary, retry, metadata, heartbeat, and downstream writers use atomic file replacement but do not share one end-to-end transaction. Overlapping read-modify-write operations can lose updates. The pending WhatsApp object is not an acknowledged multi-batch outbox and can be overwritten before successful delivery.

## 6. Failure behavior

- Missing credentials, HTTP errors, malformed activity responses, or other request failures retain prior data and suppress a success message.
- HTTP 400 creates up to **three** delayed retry attempts, each scheduled five minutes after failure. Other failure classes have no dedicated retry budget.
- Metadata failures do not roll back accepted sales.
- The heartbeat silently skips when the 08:00 freshness gate is not met; there is no later automatic replay.
- Scheduler completion is not proof that stdout reached Discord or that the marketplace page was exhaustive.

## 7. Privacy and backup

Private data includes contracts, onboarding baselines, wallets, aliases, raw activity payloads, credentials, destination IDs, pending delivery content, and logs. Public/source snapshots must contain only reviewed source and documentation, never live JSON state.

The sales source-only manifest includes the primary collector, retry, metadata worker, heartbeat, disabled WhatsApp consumer, and shared backup utilities. It does not restore private state, so source restoration requires a separately secured state recovery or an explicitly approved silent rebaseline.

The currently enabled daily backup is not healthy. The open scheduler incident shows the PRD refresh failing because the scheduled Python environment lacks the DOCX library. No backup push was attempted in this review. Existing repository history and old data-bearing files remain outside the guarantees of a clean source snapshot.

## 8. Verification and remaining requirements

Programmatic review verified the **128**-collection category totals, the five daily primary occurrences, heartbeat/retry/enrichment schedules, the disabled WhatsApp state, and current retention constants. It did not verify provider schema, current activity completeness, payment-asset correctness, delivery receipt, or remote backup state.

Required engineering work before claiming resilient coverage:

1. Implement cursor pagination with a durable watermark and bounded overlap.
2. Validate and display payment asset and quantity.
3. Replace the single pending WhatsApp object with an acknowledged outbox if that route is re-enabled.
4. Coordinate state writers under a shared transaction/lease.
5. Add durable heartbeat debt/catch-up.
6. Repair the scheduled backup environment and verify a remote commit separately.

<!-- automated-drift:start -->
**Observed implementation fingerprint:** `bf1b6f22a0322ac2267e0a7eccb5cd6a7369968736c3a5b7a5df2b9ecd8b8e8d`
**Automated drift status:** changed or unreviewed; substantive review required. Hash comparison is not a requirements review.
<!-- automated-drift:end -->
