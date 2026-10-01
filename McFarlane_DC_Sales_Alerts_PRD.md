# Product Requirements Document — MTD Completed-Sale Alerts (all approved categories)

**Version:** 2.0
**Agent source audit:** 2026-09-16; local code and recurring configuration only, no human approval, API or outbound test implied.
**Status:** Active; known coverage/delivery limitations below.
**Compatibility filename:** McFarlane_DC_Sales_Alerts_PRD. The DC filename no longer describes the entire scope.
**Private state:** HERMES_HOME/price-watches/mcfarlane-dc-sales.json (not backed up).

## Purpose, scope and schedule

Detect newly completed marketplace sales within the approved private allowlist, independently of the smaller Exotic listings watch. Current saved scope is 121 collections: DC 70, Spawn 20, UFC 12, Universal 7, McFarlane Dragons 7, Walking Dead 2, McFarlane Digital 2 and BRZRKR 1. These counts describe inspected configuration, not independently validated live market coverage.

- Primary no-agent job invokes scripts/run_mtd_sales_monitor.py, which executes price-watches/run_mcfarlane_dc_sales.py. The similarly named legacy run_mcfarlane_dc_monitor.py is not the primary runtime.
- Primary checks: 00:00, 08:00, 12:00, 16:00 and 20:00 America/New_York.
- Saved-state-only WhatsApp stage runs at minute 15 of those hours. HTTP-400 retry and one-collection metadata enrichment poll every five minutes.
- A separate saved-state last-five heartbeat runs at 08:05, gated on last_successful_check_at being today in hour 08. It does not validate an actual primary execution-ledger occurrence or maintain owed/replay state. If the check completes after the scheduled heartbeat, a later automatic catch-up is not implemented by this script.
- One-off samples/reviews are not recurring requirements and are excluded from restore schedules.

## Actual collection implementation

The primary calls Rarible POST /v0.1/activities/search with POLYGON, SELL, the exact collection-ID strings, LATEST ordering, size 1000 and a baseline-date from field. Credentials come only from RARIBLE_API_KEY; browser-like User-Agent and Accept headers are sent. Missing credentials, HTTP failures or an absent activities array retain saved data and return silent output.

Returned records are accepted only when type is exactly SELL, not reverted, in the allowlist and not already known by activity ID. Category and per-collection onboarding dates suppress older history. Query-local records are also deduplicated. Recent history is bounded to 10 records in the inspected source; the oldest-first new batch updates collection last_sale and the pending WhatsApp batch.

Item metadata supplies item name and the exact Rarity attribute; failures degrade to Unknown rather than aborting a valid sale. Missing collection display names get a best-effort priority lookup, falling back to the collection identifier. Buyer and seller wallets remain private; local unique aliases from the canonical `mcfarlane-wallet-aliases.json` database shared with Exotic and tracked-wallet monitors are preferred for display, otherwise only a nine-character wallet suffix is shown. The saved-state-only recurring-wallet audit reports distinct repeated wallets still unresolved by that database without making marketplace or notification calls. Metadata lookups use 10-second sleeps in the current primary, not a universal 15-second marketplace pacing guarantee.

## Known correctness limits — do not describe as complete coverage

- The actual primary performs ONE activity page request. It does not follow a continuation cursor or prove page exhaustion. More than 1000 matching events can be missed; the saved cursor field is not evidence of pagination.
- The primary accepts only top-level SELL. Accepted bids are covered only if the provider represents completion as SELL; independent ACCEPT_BID record coverage is not implemented here.
- The code does not advance baseline.newest_sale after the batch. It relies on initial/category baselines and the recent 10-event ID window; older events outside that window can be reconsidered when returned. A robust persisted pagination/watermark/overlap contract remains required.
- Every rendered primary sale line labels price POL without validating the payment asset. Non-POL sales can be mislabeled. Quantity is saved but omitted in the current outbound line. Time is a truncated API date string, without an explicit timezone label.
- Metadata failure does not invalidate the sale; therefore the previous PRD claim that any metadata failure retains the entire baseline was inaccurate. Collection fallback can expose a contract ID instead of a friendly pending-name label.
- Sales primary, retry, metadata and downstream writers use atomic replacement but do not share the Exotic execution lease. Overlapping read-modify-write operations can lose updates.
- A new batch overwrites pending_whatsapp_sale_alert rather than merging all undelivered events. Delivery consumption is not an acknowledged outbox transaction; failed scheduler delivery can lose replay and overlapping batches can overwrite pending events.

## Retry and enrichment

On an HTTP 400 the primary creates a five-minute due marker with three attempts. The gated retry runner is silent when no marker is due and passes MTD_HTTP400_RETRY=1; each failed retry decrements the budget. A valid parsed activities response clears the marker. Exhaustion removes it, so no automatic retry is due until a later primary failure creates a new budget. This differs from Exotic's retained generation-scoped exhausted marker. Other errors do not create this HTTP-400 budget.

The metadata worker handles one pending eligible collection per tick, prioritizing collections referenced by sale records/queues before catalog-only work. A failure cools that collection down; no pending work means no request. It writes state and a readable metadata progress report. Private category onboarding baselines must be restored or rebuilt silently before enabling alerts for a category.

## USD valuation and privacy

The primary persists API priceUsd, falling back to amountUsd, then an already-cached date-keyed POL/USD rate. It does not fetch missing historical rates itself. The older cache_mcfarlane_sale_usd.py is an unscheduled one-off migration containing embedded historic event mappings and touching both monitors, not a general rate fetcher or runtime dependency; it is deliberately excluded from source-only backups. A missing rate produces USD unavailable. Historical sale USD must not be repriced from current spot.

Raw wallets, aliases, Name Tags, delivery destinations, API credentials and raw activity payloads are private. Backup policy is now source-only rather than recursive field removal from raw state: arbitrary provider payloads can hide identities in unexpected nested fields, so denylist scrubbing is not sufficient.

## Notifications

- Successful primary no-sale result prints a short Discord status (the installed string still says MTD DC Sales Alert despite expanded scope). Failed checks are silent rather than successful heartbeats.
- New sales are aggregated into one message with one CRLF-separated line per sale, category, collection, item, rarity, price/USD, masked buyer/seller and sale time. The current omissions/mislabeling risks are listed above, not represented as fulfilled requirements.
- WhatsApp reads pending state only, adds the MTD Sales Alert heading and remains silent without undelivered activity. It makes no marketplace request.
- The independent 08:05 saved last-five heartbeat is not a new-sale alert. It renders at most five recent saved sales and may show older history; it is not a live last-five query.

## Source-only backup and restore

The explicit manifest now includes the actual primary Python wrapper and collector, HTTP-400 retry, WhatsApp downstream, 08:05 heartbeat, metadata worker, shared backup/PRD automation and offline tests. RESTORE.md and restore-config.json supply dependency requirements, relocation placeholders and disabled recurring schedules. They intentionally exclude exact roster/contracts, baseline/history, raw activity state, wallet aliases, delivery IDs, credentials, private URLs, logs, environments and browser profiles.

Restore requires Python 3.11+, the declared packages, Hermes and separately supplied private state or an explicitly approved silent rebaseline. Alias and daily-rate JSON files must exist (empty structures are acceptable for degraded display). Preserve private dedupe/pending state only through a separate trusted recovery process; do not replay history as new sales. No scheduled live test was performed for this review.

Daily backup detects identical source snapshots, enforces one ET-day success/push-attempt cap before staging, refuses dirty or legacy-data-bearing repositories, stages only explicit files, and verifies a successful push against the remote commit. Existing git history is not sanitized by creating a new source snapshot. PRD automation records drift using all manifest sources and stable relevant schedule/scope semantics plus allowlisted policy declarations; changed hashes are not a substantive review and declarations may lag implementation. DOCX follows Markdown content, not volatile scheduler telemetry. Snapshot verification rejects unlisted files and scans DOCX text, metadata and external relationships.

The enabled daily backup remains at 23:50 America/New_York. The inspected repository still contains tracked legacy monitor data and an untracked metadata script. The source-only backup intentionally refuses this repository until the owner reviews/quarantines legacy files and cleans the worktree. No automatic cleanup, history rewrite or remote push was performed by this offline audit.

<!-- automated-drift:start -->
**Observed implementation fingerprint:** `fd48ced8d4eb444e37efbf5812585bb0fb9820c75ad8bcc78f4156103f1bed93`
**Automated drift status:** changed or unreviewed; substantive review required. Hash comparison is not a requirements review.
<!-- automated-drift:end -->
