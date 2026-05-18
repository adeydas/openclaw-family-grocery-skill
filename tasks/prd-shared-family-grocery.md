# PRD: Family Grocery Skill

## Introduction

An OpenClaw skill that manages a grocery list organized by store. Items are added, removed, and viewed with store-aware grouping, web-verified addresses and availability, and category-based store assignment.

---

## Goals

- Grocery list organized by store (with address); displayed as store → [item, qty]
- Smart store assignment: user-specified, fuzzy item-mapped, category-defaulted, or unassigned pending mapping
- Image-based adds using vision to identify grocery items from photos
- Attribution of changes with timestamps so you know when items were added or removed
- Graceful fallback to `Unassigned` when no saved item mapping or category mapping exists

---

## User Stories

### US-001: User initializes the skill
**Description:** As a user, I want to set up the grocery skill so I have a data location to work from.

**Acceptance Criteria:**
- [ ] If no path is configured, skill prompts: "What path should I use for the grocery data? (e.g. /Users/Shared/grocery)"
- [ ] Skill creates the directory if it doesn't exist (`mkdir -p`)
- [ ] Skill initializes `config.json`, `list.md`, `history.md`, `safety.json` in that path
- [ ] Skill saves path to OpenClaw memory
- [ ] Skill confirms setup: "Setup complete. Your grocery list is ready at `[path]`."

### US-002: User adds an item to the list
**Description:** As a user, I want to add an item to the grocery list so I know what to buy.

**Acceptance Criteria:**
- [ ] User can say "Add [item]" or "Add [qty] of [item]"
- [ ] User can also send an image of an item and ask to add it
- [ ] Skill uses vision to identify the grocery item from the image
- [ ] Skill extracts visible item details when possible, including variant/descriptor and package size
- [ ] Before adding, skill checks `list.md` for an existing entry for the same item (case-insensitive, fuzzy match e.g. "eggs" matches "egg")
- [ ] If duplicate found: "Eggs (x12) was already added on Mar 10. Add more or update quantity?"
- [ ] If user confirms duplicate or updates qty, merge into single entry with updated quantity; log the merge in `history.md`
- [ ] If no duplicate, skill resolves store: user input → fuzzy item mapping → category mapping → unassigned
- [ ] If the user explicitly assigns an item to a store, skill saves that item→store mapping for future use
- [ ] Fuzzy item mapping handles close variants (e.g. `milk` matches `2% milk` and `1% milk`)
- [ ] If web search tool is available, skill searches "[item] available at [store name] [store address]" to verify; reports result: "Confirmed available at [store]" or "Couldn't confirm availability — adding anyway"
- [ ] If web search unavailable, skill notes: "Web search unavailable — adding to [store] based on saved preference/category"
- [ ] If no mapping exists, skill adds the item under `Unassigned`
- [ ] Item is added to `list.md` under the correct store section with qty and timestamp
- [ ] Add confirmation includes the timestamp the item was recorded
- [ ] If the item was identified from an image, the add confirmation says so
- [ ] If the item is unassigned, the user is told it should be mapped to a store
- [ ] Skill asks if there are fallback stores if none are already recorded for that item category

### US-003: User removes an item from the list
**Description:** As a user, I want to remove an item once it's been bought or is no longer needed.

**Acceptance Criteria:**
- [ ] User can say "Remove [item]" or "I got the [item]"
- [ ] If item appears under multiple stores, skill asks which one to remove from (or all)
- [ ] Removal is logged to `history.md` with timestamp and action
- [ ] Skill confirms removal: "[Item] removed from [store]."

### US-004: User views the grocery list
**Description:** As a user, I want to see the current list organized by store so I can shop efficiently.

**Acceptance Criteria:**
- [ ] User can say "Show me the grocery list" or "What do we need?"
- [ ] Output groups items by store, with store name and full address as the heading
- [ ] Each item shows: name, quantity, and timestamp added
- [ ] Items with no store assigned appear under an "Unassigned" section at the bottom
- [ ] Empty list shows: "The grocery list is empty."
- [ ] End with total item count across all stores
- [ ] Format example:
  ```
  🏪 Whole Foods (123 Main St, Anytown) — Mon–Sat 8am–9pm, Sun 9am–7pm
  - Milk, 2L — added on 2026-03-10
  - Eggs, x12 — added on 2026-03-11

  🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm
  - Olive oil, 3L — added on 2026-03-09

  📋 Unassigned
  - Batteries, x4 — added on 2026-03-12

  Total items: 4
  ```

### US-005: User sets primary store and store list
**Description:** As a user, I want to define known stores so the skill has defaults and can match items correctly.

**Acceptance Criteria:**
- [ ] User can say "Add store [name]" or "Add store [name] at [address]" to register a store
- [ ] If web search is available, skill searches for the store's address and presents the result: "Found: Whole Foods — 123 Main St, Anytown. Is this the right location? (yes / enter correct address)"
- [ ] If user confirms, that address is saved; if user provides a different address, the user-provided address is saved
- [ ] If web search is unavailable and no address was provided, skill prompts: "What's the address for [store]?"
- [ ] Confirmed store is written to `config.json`
- [ ] User can designate one store as primary: "Set [store] as primary store"
- [ ] User can set fallback order: "Fallback order: Whole Foods → Costco → Target"
- [ ] Registered stores are used as options when asking the user which store for a new item

### US-006: Skill assigns item to store by category when store is unknown
**Description:** As a user, I want items I add without specifying a store to automatically go to the right place.

**Acceptance Criteria:**
- [ ] Skill maintains a category→store mapping in `config.json` (e.g., produce → farmers market, bulk → Costco)
- [ ] User can update category mappings: "Assign produce to [store]"
- [ ] Skill maintains an item→store mapping in `config.json` for learned user preferences
- [ ] When user explicitly maps an item to a store, that mapping is reused for fuzzy future matches of the same item
- [ ] When user doesn't specify a store for an item, skill checks fuzzy item mapping first, then category mapping, then falls back to `Unassigned`
- [ ] Skill tells the user what assignment was made: "Added to Whole Foods (produce category default)"

### US-007: User maps an unassigned or recurring item to a store
**Description:** As a user, I want the skill to remember where I usually buy a specific item so I don't have to repeat it.

**Acceptance Criteria:**
- [ ] User can say "Map milk to Whole Foods" or explicitly assign a store while adding an item
- [ ] Skill saves a normalized item→store mapping in `config.json`
- [ ] Future fuzzy variants of the same item use the saved mapping automatically
- [ ] Skill confirms: "I'll remember that milk goes to Whole Foods next time."

---

## Functional Requirements

- FR-1: All data lives under a user-specified local path, initialized on first run
- FR-2: `config.json` stores: primary store, store list (name + address + hours), fallback order, item→store mappings, category→store mappings
- FR-3: `list.md` stores current items grouped by store; each entry: item, qty, store, timestamp
- FR-4: `history.md` logs all additions and removals with timestamp and action
- FR-5: Path is persisted to OpenClaw memory on first use
- FR-6: Every write to `list.md` includes a timestamp, and list output shows that timestamp next to each item
- FR-7: When adding an item, skill always resolves the store before writing (via user input → fuzzy item mapping → category mapping → unassigned, in that order)
- FR-8: When web search tool is available, skill searches for item availability at the target store before confirming
- FR-9: Store headings in list output always show full name + address
- FR-10: Before adding any item, skill checks for duplicates (case-insensitive, fuzzy match) and prompts user to merge or confirm
- FR-11: Duplicate merges are logged to `history.md`
- FR-12: History is surfaced on request (e.g. "what changed recently?") — not proactively pushed
- FR-13: When a new store is added, skill web-searches for its address, presents the result for user confirmation, and falls back to prompting for the address if search is unavailable or user rejects the result
- FR-14: Explicit user item→store assignments are saved and reused for future fuzzy item matches
- FR-15: If no item mapping or category mapping exists, the item is added to `Unassigned` and the user is told it should be mapped
- FR-16: If the user sends an image, the skill uses vision to identify the grocery item and routes the extracted item through the same duplicate, mapping, and add flow

---

## Non-Goals

- No real-time push notifications when the list changes
- No mobile app or UI — purely an OpenClaw skill interaction
- No meal planning — this skill handles what to buy, not what to cook
- No receipt scanning or barcode support
- No price tracking or budget management
- No automatic item reordering or smart replenishment
- No integration with external grocery APIs or ordering systems
- No multi-user or shared access support

---

## Data File Structure

```
[shared-path]/
├── config.json        # Stores, categories, primary store, fallback order, item mappings
├── list.md            # Current grocery list, grouped by store
├── history.md         # Log of all adds/removes
└── safety.json        # Food safety risks and alternatives
```

### config.json schema
```json
{
  "primary_store": "Whole Foods",
  "stores": [
    { "name": "Whole Foods", "address": "123 Main St, Anytown", "hours": "Mon–Sat 8am–9pm, Sun 9am–7pm" },
    { "name": "Costco", "address": "456 Oak Ave, Anytown", "hours": "Mon–Fri 10am–8:30pm, Sat 9:30am–6pm" }
  ],
  "fallback_order": ["Whole Foods", "Costco", "Target"],
  "item_store_map": {
    "milk": "Whole Foods",
    "eggs": "Costco"
  },
  "category_store_map": {
    "produce": "Whole Foods",
    "bulk": "Costco",
    "electronics": "Target"
  }
}
```

---

## Technical Considerations

- Path is the single source of truth
- Web search is optional; skill degrades gracefully when unavailable
- Skill should read `config.json` on every invocation to pick up any changes

---

## Success Metrics

- Items are correctly categorized to the right store ≥ 90% of the time without user correction
- List output is always grouped by store with address, zero unformatted dumps

---

## Open Questions

None.
