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
├── config.json    # Stores, primary store, fallback order, category→store map, item→store map
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
| Health notices | `health-notices.md` |

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
- Assigns items to stores and learns item→store preferences over time
- Uses the agent's vision capabilities to identify grocery items from images
- Checks item availability and store addresses via web search (when available)
- Checks Canada public health notices for active outbreaks when adding items
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
Resolution order: user input → fuzzy item mapping → category mapping → unassigned.

See `lists.md` for full add flow including duplicate detection and web search.

### 2b. Image-based adds use vision first
If the user sends an image of an item to add, always use the agent's vision capabilities to identify the product before continuing.

Extract when possible:
- item name
- variant or descriptor (for example `2% milk`, `large eggs`, `salted butter`)
- quantity or package size if clearly visible

Then normalize to a reusable fuzzy item key for mapping and duplicate checks.

If the image is ambiguous, use the best reasonable identification and say so briefly in the add confirmation.

### 2a. Learn item→store mappings from the user
If the user explicitly assigns an item to a store, save that preference in `config.json` and reuse it for future fuzzy matches of the same item.

Examples:
- `milk` should match `2% milk` and `1% milk`
- `eggs` should match `large eggs`
- matching must be case-insensitive and tolerant of simple descriptors, singular/plural, and quantity/style variants

### 3. Health notice check on every add
When adding an item, check Canada public health notices for active outbreaks related to the item. If a match is found, show a warning after the add confirmation. See `health-notices.md` for the full flow.

### 4. Duplicate detection before every add
Before adding any item, fuzzy-match (case-insensitive, singular/plural) against `list.md`. If a match exists, tell the user when it was added, then ask whether to merge quantities or add separately. Log merges in `history.md`.

### 5. Every write is timestamped
Every entry in `list.md` and `history.md` must include an ISO timestamp.

### 5a. List views always show item timestamps
When displaying grocery items, always show the item's add timestamp next to it, whether the user is viewing one store or the full list.

### 6. Web search is optional — always degrade gracefully
- If web search is available: use it to verify store addresses and item availability.
- If unavailable: proceed without it, note the limitation to the user once.
- Never block an action waiting for web search.

### 7. Store headings always include address
When displaying the list, format each store heading as:
`🏪 [Store Name] ([Full Address]) — [Store Hours]`

If store hours are missing, resolve them before displaying: web search → confirm with user → save to `config.json`. If search unavailable, ask user. If user skips, omit hours from heading. This ensures migration from older configs that lack store hours.

Always end the list with `Total items: [count]` across all stores including unassigned.

After "Total items", read `safety.json` fresh and fuzzy-match every current-list item against the `risks` entries. Also check Canada public health notices for active outbreaks matching any current-list item (see `health-notices.md`). Combine both into a single safety section:

```
⚠️ Safety notes:
• [Item] — [Risk from safety.json]. Alternatives: [alt1], [alt2].
• [Item] — Active health notice: [Risk summary]. See: [URL]
```

Omit the section entirely if no current-list items have a safety entry or health notice match.

## Output Contract

Use these formats exactly unless the user explicitly asks for a different presentation.

### Setup complete

```
Setup complete. Your grocery list is ready at [path].
```

### Add item

Base confirmation:

```
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If the item was extracted from an image, prepend:

```
Identified from image: [item] ([qty]).
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If the image-based identification is approximate, prepend instead:

```
Identified from image: [item] ([qty]) (best match).
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If store assignment was inferred from a fuzzy item mapping, include that in a short sentence before the confirmation:

```
Adding to [store name] (saved item mapping).
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If the user explicitly assigned the item to a store and that mapping was saved for future use, append:

```
I'll remember that [normalized item] goes to [store name] next time.
```

If store assignment was inferred from category mapping, include that in a short sentence before the confirmation:

```
Adding to [store name] ([reason]).
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If there is no fuzzy item mapping and no category mapping, add the item to `Unassigned` and tell the user exactly this:

```
Added [item] ([qty]) to Unassigned on [YYYY-MM-DD].
[Item] is currently unassigned and should be mapped to a store.
```

If the item came from an image and resolved to `Unassigned`, combine the two behaviors in this order:

```
Identified from image: [item] ([qty]).
Added [item] ([qty]) to Unassigned on [YYYY-MM-DD].
[Item] is currently unassigned and should be mapped to a store.
```

If availability could not be confirmed but the item was still added:

```
Couldn't confirm availability at [store name] — adding anyway.
Added [item] ([qty]) to [store name] on [YYYY-MM-DD].
```

If there is a health notice match, append:

```
⚠️ Health notice: [Item] is linked to an active public health outbreak — [Risk summary]. [Key advice point]. See: [URL]
```

### Duplicate found while adding

Ask exactly in this shape:

```
[Item] ([qty]) was already added on [Mon DD]. Add more, update quantity, or cancel?
```

### Remove item

Single match:

```
[Item] removed from [store].
```

Multiple matches:

```
I see [item] at [store A] and [store B]. Remove from which? (both / [store A] / [store B])
```

Not found:

```
I don't see [item] on the list.
```

### Grocery list view

When showing the full list or a per-store view, render items in this exact shape:

```markdown
🏪 [Store Name] ([Full Address]) — [Store Hours]
- [Item], [qty] — added on [YYYY-MM-DD]
- [Item], [qty] — added on [YYYY-MM-DD]

🏪 [Store Name] ([Full Address]) — [Store Hours]
- [Item], [qty] — added on [YYYY-MM-DD]

📋 Unassigned
- [Item], [qty] — added on [YYYY-MM-DD]

Total items: [count]
```

Rules:
- Always use `- [Item], [qty] — added on [YYYY-MM-DD]` for every grocery item line.
- Always include the address in store headings.
- Include `— [Store Hours]` only when hours are known.
- Show `📋 Unassigned` only when unassigned items exist.
- Keep one blank line between sections.
- After `Total items: [count]`, append the safety section only when needed.

Safety section format:

```markdown
⚠️ Safety notes:
• [Item] — [Risk from safety.json]. Alternatives: [alt1], [alt2].
• [Item] — [Risk from safety.json]. No alternatives on file.
• [Item] — Active health notice: [Risk summary]. See: [URL]
```

Empty list:

```
The grocery list is empty.
```

### Stores view

Use this exact structure:

```markdown
Primary: [Store Name] — [address]
Fallback order: [Store A] → [Store B] → [Store C]

All stores:
- [Store Name] — [address]
- [Store Name] — [address]
```

### Item mappings view

When the user asks to show saved item mappings, use:

```markdown
Saved item mappings:
• [normalized item] → [store name]
• [normalized item] → [store name]
```

### History view

Surface history entries in plain language, one per line:

```markdown
Added [item] ([qty]) on [Mon DD].
Removed [item] from [store] on [Mon DD].
Merged: [item] [old qty]+[new qty]→[merged qty] on [Mon DD].
```

### Safety list view

When the user asks to show all food safety notes, use:

```markdown
Food safety notes:
• [Item] — [Risk]. Alternatives: [alt1], [alt2].
• [Item] — [Risk]. No alternatives on file.
```

---

## Common Traps

- Reading from a stale cached config → always reload `config.json` at startup
- Adding an item without resolving a store first → always confirm store before writing to `list.md`
- Showing a list dump without store grouping → always group by store with address heading
- Forgetting to timestamp changes → every write must include a timestamp
- Blocking on web search when unavailable → degrade gracefully, proceed without it
- Skipping the health notice check when adding → always check Canada public health notices on add (gracefully skip if web unavailable)
- Asking for the shared path every session → it must be in OpenClaw memory after first use
