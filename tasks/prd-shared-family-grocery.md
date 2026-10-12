# PRD: Family Grocery v3 — Shared Mobile Checklist

## Product and scope

Family Grocery combines an OpenClaw skill, used through WhatsApp, with a mobile webpage for checking off groceries. A household shares one list and one private link, without accounts or individual attribution. OpenClaw runs on a VPS; its existing Nginx server serves the checklist at `https://hadol.deydas.com/grocery/`.

The first web version supports viewing and removing items. Adding items, changing quantities, managing stores, interpreting photos, and maintaining safety information remain OpenClaw workflows. Implementation and deployment templates are included in the repository; actual VPS deployment is a separate operation following [the runbook](../docs/vps-setup.md).

## Goals

- Let shoppers open the current grocery list from WhatsApp and remove saved items with large mobile checkboxes.
- Keep several shoppers and WhatsApp changes consistent without lost updates or duplicate removal history.
- Limit shared-link access to four hours, with an explicit Close action that immediately revokes access for everyone using that link.
- Preserve store preferences, vision input, duplicate handling, timestamps, safety notes, and history from the existing skill.
- Provide reproducible setup and recovery instructions for an agent administering the VPS's existing Nginx installation.

## User flows and acceptance criteria

### US-001: Initialize or migrate the household

- Persist `family_grocery_path`, `family_grocery_cli`, and `family_grocery_public_url` in OpenClaw memory.
- Initialize the configured private local directory through the CLI before starting the service.
- Use `grocery.sqlite3` as the authoritative store for items, history, revisions, retry receipts, shared links, and browser sessions.
- Import supported legacy list/history Markdown once; retain originals and reject unsupported rows for review rather than silently omitting them.
- Interpret legacy timestamps without a timezone as UTC and disclose that migration assumption.
- Preserve existing configuration and safety data. Pause legacy writers during migration and replace their direct Markdown writes with CLI calls.
- Share state access between the dedicated non-root service and the actual OpenClaw OS account, with no world access.

### US-002: Add items through WhatsApp

- Parse natural-language names and quantities; use a default quantity of one when unspecified.
- For product photos, use the agent's vision to identify the item, visible variant, and package size. Identify approximate matches as such in the confirmation.
- Reload configuration and current database items before fuzzy duplicate detection. Match case-insensitively and tolerate ordinary singular/plural or descriptor variants.
- When a duplicate exists, offer adding more, updating quantity, or cancelling. Log a merge/update once and preserve the item's original added timestamp.
- Resolve stores in this order: explicit user choice → learned item mapping → category mapping → Unassigned.
- Save explicit item-to-store choices for future fuzzy matches. Tell users when an item remains unassigned.
- When available, use web tools to check store addresses, hours, and item availability. Distinguish confirmed information from unavailable/unverified information and continue gracefully if web access is unavailable.
- Check Canadian public health notices on adds and surface relevant warnings according to the health-notice workflow.
- Submit a list revision with each add so a concurrent edit forces a fresh duplicate check. Submit the item's version for a merge/update so a concurrent quantity change cannot be overwritten.
- Give each logical change an operation ID, reusing it only when retrying that same request. Confirm success only after the CLI reports a saved change.

### US-003: Request and share the mobile checklist

- A normal “show grocery list” request returns the private mobile link, current item count, and original expiry information.
- Reuse the single active link until it expires or is closed. Opening or requesting it never refreshes its deadline.
- A new link has an absolute TTL of four hours from server creation time.
- Every household member can use the same link without signing in or identifying themselves.
- The link secret is in the URL fragment. The browser exchanges it for an HttpOnly session cookie, then removes the secret from the address bar.
- The public page shell and previews contain no list data. A private session is required to read the list or change it.
- If the user explicitly requests a text list, or the link service is unavailable, the agent can show current CLI data in the established store-grouped text format. Never fabricate a working link.

### US-004: Shop with checkboxes

- Render a responsive, accessible page with store groups, quantities, original added dates, and remaining-item count.
- Display configured store addresses/hours and put Unassigned last. Missing optional metadata must not hide the saved grocery list.
- Provide a clear empty-list state, loading/saving feedback, connection status, and retryable error messages.
- Checking an item removes that exact saved entry and records one timestamped removal. Remove the visible row after the server confirms success.
- Poll normally every three seconds while connected and refresh after reconnecting; expose no offline queue that could later remove outdated items.
- Show saved safety notes and matching cached health notices with the cache's check time when available. The webpage does not itself run live health searches.

### US-005: Handle simultaneous household activity

| Concurrent situation | Required result |
| --- | --- |
| Two shoppers remove different items | Both changes persist. |
| Two shoppers remove the same item | One removal and one history entry. |
| A quantity changes before an old checkbox is submitted | Reject the stale version and refresh the row before allowing removal. |
| An item is removed and then re-added | The replacement has a new ID; old actions cannot remove it. |
| A successful request is retried after a lost response | Return the prior result without a second change/history entry. |
| A user adds through WhatsApp while browsers are open | Browsers receive the updated list through polling. |
| An old tab shares a browser cookie with a newer link | Link IDs prevent the old tab from changing or closing the newer link. |

- Use SQLite transactions for authorization, version/revision checks, changes, history, and retry receipts.
- Support multiple Gunicorn workers and browser users against one local database, rather than relying on a process-local lock.
- Keep the database on the VPS's local filesystem. This version does not coordinate database files across multiple hosts.

### US-006: Close or expire shared access

- Display a visible **Close** button and explain that it expires access for everyone using that link.
- Show the absolute expiry time and remaining time on the page.
- Closing revokes the link and its sessions server-side; other open pages detect revocation on their next request.
- Reject list reads and changes after closure or at the four-hour deadline, even with a previously valid session cookie.
- An expired/closed page directs the user to ask for a new link in WhatsApp. The saved list and history remain intact.
- Closing the browser tab does not revoke the link. Restarting the service does not reset its deadline or lose revocation state.
- Expose link creation and administrative revocation only through the trusted local CLI, not public unauthenticated endpoints.

### US-007: Preserve stores, mappings, safety notes, and history

- Store names, addresses, hours, primary store, fallback order, item mappings, and category mappings remain in `config.json`.
- Users can add stores, select a primary store, change fallback order, assign categories, and teach item preferences through WhatsApp.
- Confirm researched store locations/hours with the user as needed; persist only the accepted values.
- Food-safety risks and alternatives remain user-maintained in `safety.json`.
- Health notices are checked by OpenClaw on adds/list requests when web access is available; optionally persist an explicitly timestamped `health-notices.json` cache for the mobile page. Do not present cached information as a fresh check.
- Reload metadata on use and replace JSON files atomically to avoid exposing partial writes to browser readers.
- “Remove milk” and “I got the eggs” resolve saved IDs and versions through the CLI. Ask which entry to remove when the user intent is ambiguous across stores.
- History records what changed and when, without identifying household members; surface it on request with useful action/date filtering.

## Architecture and interfaces

```text
WhatsApp → OpenClaw → family-grocery CLI → shared storage implementation
Phone → Nginx /grocery/ → Python WSGI API → shared storage implementation
                                             ↓
                              local SQLite + JSON metadata
```

| Component | Responsibility |
| --- | --- |
| Skill Markdown | Intent parsing, vision, fuzzy matching, store/safety workflows, CLI use |
| `grocery_service/store.py` | Transactions, IDs/versions, migration, history, link/session lifecycle |
| `grocery_service/cli.py` | Trusted local JSON interface for init/list/add/update/remove/history/link/close-link/export/backup |
| `grocery_service/web.py` | Static mobile assets and authenticated session/list/remove/close endpoints |
| `grocery_service/static/` | Phone UI, polling, expiry display, errors, and checkbox actions |
| Gunicorn + systemd | Non-root application process, loopback listener, restart management |
| Existing Nginx | Existing HTTPS domain and `/grocery/` reverse-proxy routing |

Runtime requirements are Python 3.10+ and Gunicorn for production. SQLite and the WSGI application use Python's standard library. No JavaScript build, separate database server, or native phone application is required.

## Privacy and deployment requirements

- Treat a shared link as a bearer credential: anyone holding it has view/remove/close access. Do not post keys, cookies, or session state to logs or public artifacts.
- Use HTTPS and Secure, HttpOnly, SameSite cookies in production; allow insecure cookies only on explicitly configured loopback HTTP development URLs.
- Enforce the configured same origin for state-changing browser requests. Return non-cacheable responses and prevent framing and unintended referrer disclosure.
- Keep Gunicorn on `127.0.0.1:8787`; the public network reaches the existing Nginx HTTPS listener only.
- Add scoped locations inside the existing `hadol.deydas.com` TLS server block. Preserve unrelated routes, certificate settings, and renewal arrangements; do not replace the whole site.
- Preserve the `/grocery/` prefix when proxying; disable upstream/CDN caching for it. Validate with `nginx -t` before reload.
- Supply agent-ready account discovery, private backups, permissions, migration, health/authentication checks, multi-browser validation, and rollback guidance.
- Use SQLite online backups and separately preserve metadata. Markdown exports are interchange snapshots, not a complete recoverable database backup.

## Non-goals

- Individual accounts, per-person permissions, or household-member attribution.
- A native mobile app, offline writes, or push notifications to WhatsApp.
- Browser-based adding, quantity editing, or store administration in this version.
- Purchases, ordering systems, live inventory APIs, price tracking, budgets, receipt/barcode scanning, meal planning, or automatic replenishment.
- Multi-host database replication or a hosted multi-household service.

## Verification and completion criteria

- Automated tests pass using disposable directories and controlled clocks for migration, shared-link reuse, fixed TTL, revocation, stale versions, atomic history, retry handling, and simultaneous writes.
- WSGI tests verify private API authentication, origin checks, expiry/revocation enforcement, public shell behavior, and correct `/grocery/` routing.
- JavaScript passes a syntax check; the mobile UI is visually checked at phone width and exercised in a browser.
- The VPS runbook includes a two-browser smoke test in disposable state, plus passive production health checks that do not remove household items or close a live link.
- Deployment completion is reported separately from implementation completion, with the installed revision, changed Nginx file, backup location, and verification results, omitting access secrets.
