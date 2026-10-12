# Family Grocery

An [OpenClaw](https://openclaw.com) skill with a shared mobile grocery checklist. Manage groceries through WhatsApp, then open a private link to check items off while shopping. Each checkbox removes the saved item and records the change in history.

**VPS deployment:** the production URL is `https://hadol.deydas.com/grocery/`, using the domain's existing Nginx server. Follow the [VPS setup runbook](docs/vps-setup.md) for installation, migration, Nginx integration, verification, and rollback. This repository includes the implementation and setup files; it does not imply the service has already been deployed.

**Skill listing:** [ClawHub](https://clawhub.ai/adeydas/family-grocery). Version 3 also needs the Python service installed from this repository; the Markdown skill alone does not host the checklist.

## Shopping flow

1. Say **“Show me the grocery list”** in WhatsApp.
2. OpenClaw returns a private link to the current shared checklist.
3. Open it on your phone. Items show their quantities and added dates, grouped by store, with available addresses and hours. Unassigned items appear last.
4. Tap a checkbox to remove that exact item. Other open checklists refresh automatically, normally within three seconds while connected.
5. Press **Close** to expire that link for everyone. The list and history stay saved.

Everyone uses one shared link, without accounts or individual attribution. The link expires **four hours after creation**. Reopening, refreshing, sharing, or requesting it again does not extend that deadline. Repeated requests reuse the active link; the next request after Close or expiry creates a new one. The page shows the deadline and remaining time. Closing a browser tab alone does not revoke access.

Anyone holding the link can view/remove groceries and close access. Its `#key=...` secret is exchanged for a secure browser session and removed from the address bar. The bare URL and WhatsApp previews reveal no grocery data. The server enforces expiry and revocation on reads and changes, including already-open pages.

## Features

- **Concurrent shopping:** different items can be checked off together; checking the same item twice produces one removal and one history entry. Item versions reject stale changes, and stable IDs prevent an old checkbox from removing a newly re-added item.
- **Reliable saving:** failed saves leave the item visible, retrying does not duplicate history, and pages reload current state after reconnecting. There is no offline write queue.
- **Text and image input:** OpenClaw parses quantities or identifies a photographed item using its vision capability, then applies the normal duplicate and store-mapping flow.
- **Store preferences:** explicit store → learned item mapping → category mapping → Unassigned. Explicit choices teach future mappings; duplicate quantities can be merged or updated.
- **Store and safety information:** the skill can verify addresses, hours, and availability through available web tools. It maintains food-safety notes and checks Canadian public health notices. The webpage displays saved notes and an agent-refreshed notice cache; it does not conduct live web searches.
- **History:** timestamped adds, updates, merges, and removals, available through WhatsApp or the local CLI. Adding items, editing quantities, and managing stores remain WhatsApp operations in this version.

Examples:

```text
Add 2L of milk
Add eggs at Costco
Add this [with a product photo]
I got the eggs
Show me the grocery list
Map milk to Whole Foods
Assign produce to Whole Foods
What changed recently?
Add safety risk for raw chicken
```

## Architecture and data

```text
WhatsApp → OpenClaw → local family-grocery CLI ─┐
                                              ├→ SQLite list + history + access state
Phone → existing Nginx → checklist application ┘
```

The application is Python 3.10+ with SQLite and a WSGI interface. Gunicorn serves it on the VPS's loopback address; Nginx supplies the existing HTTPS entry point. It needs no separate database server or JavaScript build step.

```text
[shared-path]/
├── grocery.sqlite3       # Authoritative items, history, revisions, links, sessions
├── config.json           # Stores, hours, fallback order, item/category mappings
├── safety.json           # Saved food-safety risks and alternatives
├── health-notices.json   # Optional notice cache refreshed by OpenClaw
├── list.md               # Preserved legacy input, if present; no longer live state
└── history.md            # Preserved legacy input, if present; no longer live state
```

All grocery changes use the CLI or web service's shared transaction code. A change, its history entry, and retry receipt commit together. The CLI is a trusted local administration interface; the public API only exposes authenticated checklist operations.

## Local demo

Run from a checkout of this repository. These commands create a disposable list, add one sample item, print its private link, and start a local server. Open the printed link after the server starts; stop it with Ctrl+C.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[server]'
GROCERY_DEMO_DATA="$(mktemp -d)"
.venv/bin/family-grocery --data-dir "$GROCERY_DEMO_DATA" init
.venv/bin/family-grocery --data-dir "$GROCERY_DEMO_DATA" add --name Milk --quantity 2L --store Costco --expected-revision 0 --operation-id demo-milk-add
.venv/bin/family-grocery --data-dir "$GROCERY_DEMO_DATA" link --base-url http://127.0.0.1:8788/grocery/
GROCERY_DATA_DIR="$GROCERY_DEMO_DATA" \
GROCERY_PUBLIC_URL=http://127.0.0.1:8788/grocery/ \
GROCERY_COOKIE_SECURE=0 \
.venv/bin/gunicorn --bind 127.0.0.1:8788 --workers 2 --threads 4 --worker-class gthread 'grocery_service.web:create_app()'
```

Insecure cookies are allowed only for loopback HTTP development. Production uses HTTPS and `GROCERY_COOKIE_SECURE=1`. Follow [the VPS runbook](docs/vps-setup.md) to use `/opt/family-grocery`, `/var/lib/family-grocery`, the supplied systemd unit, and the existing Nginx configuration.

## OpenClaw integration and migration

Install the current root skill files and configure these memory values for the VPS:

| Key | Value |
| --- | --- |
| `family_grocery_path` | `/var/lib/family-grocery` |
| `family_grocery_cli` | `/opt/family-grocery/.venv/bin/family-grocery` |
| `family_grocery_public_url` | `https://hadol.deydas.com/grocery/` |

The OpenClaw process needs permission to run the CLI and access the same private state directory as the service. The runbook explains the shared Unix group and required ownership/modes. Follow [SKILL.md](SKILL.md) and [lists.md](lists.md) for CLI operations, conflict handling, and response formats.

For an existing installation, **pause old grocery writers and back up the original files first**. `family-grocery --data-dir PATH init` imports supported `list.md` and `history.md` once, preserving the originals. Unknown rows fail the import for review. Date-only item entries retain their calendar dates; timestamps with a time but no timezone are interpreted as UTC. Verify the imported count, quantities, stores, dates, and history before resuming. Replace the old skill instructions so OpenClaw stops writing Markdown directly.

An already initialized database is not reimported. `export --output-dir NEW_DIRECTORY` creates Markdown snapshots outside the live data directory. `backup --output NEW_SQLITE_FILE` makes a SQLite online backup; also back up configuration and safety metadata. Copying a live database file alone can miss committed WAL data. See the runbook for exact migration and backup commands.

## Verification

The tests use temporary data directories and controlled clocks; they do not modify household data or wait four hours:

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check grocery_service/static/app.js
node --test tests/test_frontend.cjs
```

Node 18+ is only needed for the JavaScript syntax check and frontend regression tests, not for running the service. Test simultaneous browsers, reconnect behavior, and Close in a disposable deployment before production cutover. Server-side tests cover transactions, retries, version conflicts, migration, link reuse/expiry/revocation, and API access controls. Frontend tests cover expiry display, Close, stale tabs/versions, safety matching, and retry IDs.

## Repository guide

| File or directory | Purpose |
| --- | --- |
| [SKILL.md](SKILL.md) | Agent entry point, setup, core rules, and response formats |
| [lists.md](lists.md) | CLI-backed add, remove, view, and history workflows |
| [stores.md](stores.md) | Stores, learned preferences, and category mappings |
| [food-safety.md](food-safety.md), [health-notices.md](health-notices.md) | Saved safety notes and public-health notice handling |
| [memory-template.md](memory-template.md) | Metadata formats and OpenClaw memory keys |
| [grocery_service/](grocery_service/) | Transactional storage, CLI, WSGI application, and mobile UI |
| [deploy/](deploy/), [docs/vps-setup.md](docs/vps-setup.md) | Nginx/systemd templates and deployment runbook |
| [tasks/prd-shared-family-grocery.md](tasks/prd-shared-family-grocery.md) | Version 3 product requirements |

## License

MIT
