---
name: Family Grocery
slug: family-grocery
version: 2.0.0
description: Grocery list organized by store — add, remove, and view items. Web-verified store addresses and item availability.
metadata: {"clawdbot":{"emoji":"🛒","requires":{"bins":[]},"os":["linux","darwin","win32"]}}
---

## When to Use

You need to add, remove, or view a grocery list organized by store (with address). Focus: what to buy and where, not meal planning.

## Architecture

Data lives in a user-configured local path.

```
[shared-path]/
├── config.json    # Stores, primary store, fallback order, category→store map
├── list.md        # Current grocery list, grouped by store
└── history.md     # Log of all adds, removes, and merges
```

Skill reference files:

| Topic | File |
|-------|------|
| Data file templates | `memory-template.md` |
| List operations | `lists.md` |
| Store management | `stores.md` |
| Food safety | `food-safety.md` |

## Startup Sequence

Run this every invocation, in order:

### Step 1 — Resolve shared path
1. Read shared path from OpenClaw memory (key: `family_grocery_path`).
2. If not found → this is a **first-time setup**. Go to **Init Flow** below.

### Step 2 — Load config
1. Read `[shared-path]/config.json`.
2. Check whether `[shared-path]/safety.json` exists. If not → create it with `{"risks": []}` (silent upgrade, no user prompt needed).

---

## Init Flow

Only runs when no shared path is in OpenClaw memory.

1. Ask: "What path should I use for the grocery data? (e.g. /Users/Shared/grocery)"
2. Create directory: `mkdir -p [path]`
3. Initialize files from `memory-template.md`: `config.json`, `list.md`, `history.md`, `safety.json`
4. Save path to OpenClaw memory as `family_grocery_path`
5. Confirm: "Setup complete. Your grocery list is ready at `[path]`."

---

## Scope

This skill ONLY:
- Manages the grocery list (add, remove, view)
- Tracks stores and their addresses
- Assigns items to stores (by user input, category, or primary store default)
- Checks item availability and store addresses via web search (when available)
- Surfaces change history on request

This skill NEVER:
- Makes purchases or places orders
- Plans meals or suggests recipes
- Reads or writes files outside `[shared-path]`
- Accesses live store inventory systems
- Pushes notifications when the list changes

---

## Core Rules

### 1. Always reload config on every invocation
Never cache across sessions. Always re-read `config.json` at startup to pick up any changes.

### 2. Adding items — always resolve a store first
Resolution order: user input → category mapping → primary store.

See `lists.md` for full add flow including duplicate detection and web search.

### 3. Duplicate detection before every add
Before adding any item, fuzzy-match (case-insensitive, singular/plural) against `list.md`. If a match exists, tell the user when it was added, then ask whether to merge quantities or add separately. Log merges in `history.md`.

### 4. Every write is timestamped
Every entry in `list.md` and `history.md` must include an ISO timestamp.

### 5. Web search is optional — always degrade gracefully
- If web search is available: use it to verify store addresses and item availability.
- If unavailable: proceed without it, note the limitation to the user once.
- Never block an action waiting for web search.

### 6. Store headings always include address
When displaying the list, format each store heading as:
`🏪 [Store Name] ([Full Address]) — [Store Hours]`

If store hours are missing, resolve them before displaying: web search → confirm with user → save to `config.json`. If search unavailable, ask user. If user skips, omit hours from heading. This ensures migration from older configs that lack store hours.

Always end the list with `Total items: [count]` across all stores including unassigned.

After "Total items", read `safety.json` fresh and fuzzy-match every current-list item against the `risks` entries. If any matches are found, append:

```
⚠️ Safety notes:
• [Item] — [Risk]. Alternatives: [alt1], [alt2].
• [Item] — [Risk]. No alternatives on file.
```

Omit the section entirely if no current-list items have a safety entry.

---

## Common Traps

- Reading from a stale cached config → always reload `config.json` at startup
- Adding an item without resolving a store first → always confirm store before writing to `list.md`
- Showing a list dump without store grouping → always group by store with address heading
- Forgetting to timestamp changes → every write must include a timestamp
- Blocking on web search when unavailable → degrade gracefully, proceed without it
- Asking for the shared path every session → it must be in OpenClaw memory after first use
