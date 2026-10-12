---
name: Family Grocery
slug: family-grocery
version: 3.0.0
description: Manage a shared grocery list by store and show a mobile checklist with private four-hour links. Add from text or images, check off purchases, and surface safety notes.
metadata: {"clawdbot":{"emoji":"🛒","requires":{"bins":["python3"]},"os":["linux","darwin"]}}
---

## When to Use

Add, remove, or view household groceries organized by store. The default list view is a shared mobile checklist linked from WhatsApp. Focus on what to buy and where; never make purchases, place orders, plan meals, or claim access to live store inventory.

## Runtime and Data

Version 3 requires the installed Python 3.10+ package and its `family-grocery` CLI. The mobile checklist also requires the running web service behind Nginx. Copying the Markdown skill files alone does not install these components. Follow [the VPS setup guide](docs/vps-setup.md) for `https://hadol.deydas.com/grocery/`.

The CLI and web service use the same transactional SQLite storage code. SQLite is the sole authority for current items, history, revisions, retry receipts, shared links, and browser sessions. Never edit the database directly or fall back to writing legacy Markdown.

```text
[shared-path]/
├── grocery.sqlite3       # Authoritative list/history and private authentication state
├── config.json           # Stores, addresses, hours, mappings, fallback preferences
├── safety.json           # User-maintained food safety notes
├── health-notices.json   # Optional agent-refreshed health notice cache
├── metadata.lock         # Lock shared by all JSON metadata writers
├── list.md               # Optional original legacy input, preserved after migration
└── history.md            # Optional original legacy input, preserved after migration
```

SQLite may create `grocery.sqlite3-wal` and `grocery.sqlite3-shm`; leave them to SQLite. Keep state in a private local directory shared only by the service and OpenClaw OS account. There are no household accounts or individual attribution.

| Task | Reference |
| --- | --- |
| List commands, duplicate/conflict handling, history | [lists.md](lists.md) |
| Memory keys, JSON schemas, metadata locking | [memory-template.md](memory-template.md) |
| Stores and learned mappings | [stores.md](stores.md) |
| User-maintained safety notes | [food-safety.md](food-safety.md) |
| Canada public health notices and cache | [health-notices.md](health-notices.md) |
| Installation, migration, Nginx, operations | [docs/vps-setup.md](docs/vps-setup.md) |

## Startup

1. Resolve saved OpenClaw memory keys: `family_grocery_cli` (absolute executable, normally `/opt/family-grocery/.venv/bin/family-grocery`), `family_grocery_path` (normally `/var/lib/family-grocery`), and `family_grocery_public_url` (`https://hadol.deydas.com/grocery/`). Use established deployment configuration where available; ask only for genuinely missing information and save resolved values.
2. Read `config.json`, `safety.json`, and any `health-notices.json` fresh. Every JSON modification must use the shared `metadata.lock` and atomic-replace procedure in [memory-template.md](memory-template.md).
3. Invoke the configured CLI with `--data-dir [shared-path]`. Its JSON `list` result provides current IDs, versions, and list revision. If the CLI/runtime is missing or fails, report the concrete problem; never use stale legacy files as current state.

Use an argument array where possible. If a shell is required, safely quote each argument: item names, quantities, stores, and paths are data, never shell source. Do not assume the CLI is on `PATH` or OpenClaw's environment matches the web service's.

## First-Time Setup and Upgrade

Use the installed executable and established deployment values. During an upgrade, stop **all old agents/writers that edit `list.md` or `history.md`** before importing. Back up state, then run:

```text
[family_grocery_cli] --data-dir [shared-path] init
```

`init` creates SQLite and missing default `config.json`/`safety.json`, imports recognized v1/v2 list/history rows once, and preserves original Markdown and existing JSON. A persistent marker prevents reimport even when the original list was empty. Date-only item dates stay date-only so timezone conversion cannot shift their calendar date. Legacy timestamps with a time but no timezone are interpreted as UTC; originals retain their exact previous text.

If migration reports an unsupported row, stop and reconcile it using the preserved source before retrying. Never delete unknown lines, silently skip import, or use `init --no-import` to hide an error. `--no-import` is only for an intentional, explicitly chosen fresh database. After deployment checks pass and all agents use v3, resume grocery work and save all three memory keys.

Confirm only after successful initialization and intended service checks:

```text
Setup complete. Your grocery list is ready at [path].
```

## Grocery Rules

Use [lists.md](lists.md) for commands and detailed flows.

- **Images:** use vision first for item, variant, and visible quantity; normalize a fuzzy item key. For approximate identification say `Identified from image: [item] ([qty]) (best match).`
- **Store resolution:** explicit user choice → saved fuzzy item mapping → category mapping → `Unassigned`. Learn explicit choices through locked JSON updates and confirm only after saving. A milk mapping may match `2% milk` and `1% milk`.
- **Duplicates:** fuzzy-match a fresh CLI snapshot, including case, simple descriptors, and singular/plural. Ask whether to add more, update quantity, or cancel. A confirmed merge uses `update --action MERGE`; a separate entry requires an explicit choice.
- **Concurrency:** adds use snapshot `--expected-revision`; updates/removals use exact `--id` and `--version`. Generate an operation UUID before each mutation. Retry an uncertain outcome with the same UUID and identical arguments. On a conflict, reload and reassess rather than blindly adopting a new revision/version.
- **History:** the service timestamps and commits each item change with its history event. Never append another event from the agent.
- **Health notices:** check on adds and views; append matching warnings after the result. After a successful complete check, refresh matches for every item in a fresh list snapshot, using each current item's exact name in the cache. Preserve the old file/timestamp on failure. The webpage displays cached notices, not a live health check.
- **Web lookup:** verify availability, addresses, and hours when possible; unavailable search must not block groceries. Note unavailable availability lookup once; silently skip an unavailable live health fetch while retaining known warnings.

## Default List Response

For “show my list”, “what do we need?”, or equivalent, run `list`, then `link --base-url [family_grocery_public_url]`. Copy the returned `url` exactly. Do not invent tokens, change the fragment, or publish private URLs in logs, repository files, public Pages, or search queries.

```text
Open grocery checklist — [count] items:
[exact URL returned by CLI]
Expires [actual date/time and timezone]. Close expires this link for everyone.
```

Format `expires_at` in the user's known timezone, or explicitly label UTC when unknown. An active shared link is reused with its original expiry. Never promise another four hours for a reused link. Opening, refreshing, and sharing do not renew it. **Close** revokes the link and every browser session using it; merely closing a tab does not. The next request after expiry/Close creates a fresh four-hour link.

Return a link even for `0 items`, adding `The grocery list is empty.` Open pages refresh shared changes automatically. Checking removes that exact saved entry and logs it once even when several people check it. Closure/expiry leaves groceries and history intact.

Read current safety notes and check health notices before finishing; append a safety section if applicable. Known addresses/hours appear on the page. Resolve missing hours through store management without withholding a working checklist link.

Use a text list only when explicitly requested or when link delivery/service access fails while the CLI can still read current data. Minting a token does not prove a broken or unconfigured service is reachable. Explain a known service failure and show current text; never substitute legacy files. For a requested store view, return the shared mobile link and tell the user to select that store's filter on the page. The link itself opens the whole shared list; only an explicit text request switches to a filtered text view.

## Other Response Formats

### Add and remove

```text
Added [item] ([qty]) to [store] on [YYYY-MM-DD].
[Item] removed from [store].
```

Image adds prepend `Identified from image: [item] ([qty]).`, adding `(best match)` for uncertainty. A saved explicit mapping appends `I'll remember that [normalized item] goes to [store] next time.` Unassigned adds append `[Item] is currently unassigned and should be mapped to a store.` Use the returned item's timestamp; never confirm an unsuccessful write.

Duplicate prompt:

```text
[Item] ([qty]) was already added on [Mon DD]. Add more, update quantity, or cancel?
```

For multiple store matches:

```text
I see [item] at [store A] and [store B]. Remove from which? (both / [store A] / [store B])
```

If absent: `I don't see [item] on the list.`

### Explicit text list or fallback

Group stores alphabetically, Unassigned last. Include item dates in full and filtered views, known address/hours, and count. Label a filtered total clearly; do not invent missing metadata.

```text
🏪 [Store Name] ([Full Address]) — [Store Hours]
- [Item], [qty] — added on [YYYY-MM-DD]

📋 Unassigned
- [Item], [qty] — added on [YYYY-MM-DD]

Total items: [count]
```

Omit unknown hours and empty Unassigned sections. Use `address not on file` when missing and resolve it through store management. If empty, say `The grocery list is empty.`

### Safety notes

Append only for matching current items:

```text
⚠️ Safety notes:
• [Item] — [Risk]. Alternatives: [alt1], [alt2].
• [Item] — [Risk]. No alternatives on file.
• [Item] — Active health notice: [Risk summary]. See: [URL]
```

Add-specific warning: `⚠️ Health notice: [Item] is linked to an active public health outbreak — [Risk summary]. [Key advice point]. See: [URL]`. If a live check failed, identify cached notices by their recorded check time rather than implying fresh verification.

Store/mapping formats are in [stores.md](stores.md), safety management in [food-safety.md](food-safety.md), and history output in [lists.md](lists.md). History describes what changed and when, without household-member attribution.
