# PRD: Shared Family Grocery Skill

## Introduction

An OpenClaw skill that enables multiple family members (each using their own agent instance) to collaboratively manage a shared grocery list stored on a common local path. The first user initializes the skill and becomes the admin, who can then add other users. Once added, all users have full access to add, remove, and view the shared list. Items are organized by store (with address), with availability checked via web search and defaulted by category when the user doesn't specify.

---

## Goals

- Single shared grocery list accessible to all family members via their own agents
- Admin-controlled user management; all approved users get full list access
- Items tracked per-store (with address); displayed as store → [item, qty]
- Smart store assignment: user-specified, category-defaulted, or web-search verified
- Attribution on changes so the household knows who added/removed what
- Graceful fallback to primary household store when user doesn't know where to buy something

---

## User Stories

### US-001: Admin initializes the skill
**Description:** As the first user, I want to set up the shared grocery skill so that the family has a shared data location to work from.

**Acceptance Criteria:**
- [ ] If no shared path is configured, skill prompts: "What shared path should I use for the family grocery data? (e.g. /Users/Shared/grocery)"
- [ ] Skill creates the directory if it doesn't exist (`mkdir -p`)
- [ ] Skill initializes `config.json`, `users.md`, `list.md`, `history.md` in that path
- [ ] The first user is written to `users.md` as admin with their provided name
- [ ] Skill confirms setup: "Setup complete. You are admin. Share the path `/x/y/z` with other family members."

### US-002: Admin adds a family member
**Description:** As the admin, I want to add a family member so they can access and manage the shared grocery list.

**Acceptance Criteria:**
- [ ] Admin can say "Add user [name]" and the skill appends them to `users.md` with `role: member`
- [ ] Skill confirms: "[Name] has been added. They can now access the list by identifying themselves."
- [ ] Non-admin users attempting to add users are denied: "Only the admin can add users."
- [ ] `users.md` entries include: name, role (admin/member), date added

### US-003: Skill resolves user identity from OpenClaw memory
**Description:** As a family member, I want the skill to automatically know who I am from my OpenClaw memory so I don't have to identify myself each time.

**Acceptance Criteria:**
- [ ] Skill reads the user's name from the OpenClaw memory (set once by the user telling their agent "I'm [name]")
- [ ] Skill looks up that name in `users.md`; grants access if found, denies with explanation if not
- [ ] If no name is found in OpenClaw memory, skill prompts: "I don't know your name yet. Tell me (e.g. 'I'm Nita') and I'll remember it."
- [ ] On first identification, skill saves the name to OpenClaw memory so it's never asked again
- [ ] All changes written to `list.md` include the resolved user name and timestamp

### US-004: User adds an item to the list
**Description:** As a family member, I want to add an item to the shared grocery list so everyone knows what to buy.

**Acceptance Criteria:**
- [ ] User can say "Add [item]" or "Add [qty] of [item]"
- [ ] Before adding, skill checks `list.md` for an existing entry for the same item (case-insensitive, fuzzy match e.g. "eggs" matches "egg")
- [ ] If duplicate found: "Nita already added eggs (x12) on Mar 10. Add more or update quantity?"
- [ ] If user confirms duplicate or updates qty, merge into single entry with updated quantity; log the merge in `history.md`
- [ ] If no duplicate, skill asks: "Which store? (or press Enter to use [primary store])"
- [ ] If user specifies a store, skill records it as preferred for that item
- [ ] If user doesn't specify, skill defaults to the household primary store
- [ ] If web search tool is available, skill searches "[item] available at [store name] [store address]" to verify; reports result: "Confirmed available at [store]" or "Couldn't confirm availability — adding anyway"
- [ ] If web search unavailable, skill notes: "Web search unavailable — adding to [store] based on category/preference"
- [ ] Item is added to `list.md` under the correct store section with qty, added-by, and timestamp
- [ ] Skill asks if there are fallback stores if none are already recorded for that item category

### US-005: User removes an item from the list
**Description:** As a family member, I want to remove an item once it's been bought or is no longer needed.

**Acceptance Criteria:**
- [ ] User can say "Remove [item]" or "I got the [item]"
- [ ] If item appears under multiple stores, skill asks which one to remove from (or all)
- [ ] Removal is logged to `history.md` with user name, timestamp, and action
- [ ] Skill confirms removal: "[Item] removed from [store] list by [user]"

### US-006: User views the grocery list
**Description:** As a family member, I want to see the current list organized by store so I can shop efficiently.

**Acceptance Criteria:**
- [ ] User can say "Show me the grocery list" or "What do we need?"
- [ ] Output groups items by store, with store name and full address as the heading
- [ ] Each item shows: name, quantity, added by, date added
- [ ] Items with no store assigned appear under an "Unassigned" section at the bottom
- [ ] Empty list shows: "The grocery list is empty."
- [ ] End with total item count across all stores
- [ ] Format example:
  ```
  🏪 Whole Foods (123 Main St, Anytown) — Mon–Sat 8am–9pm, Sun 9am–7pm
  - Milk, 2L
  - Eggs, x12

  🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm
  - Olive oil, 3L

  📋 Unassigned
  - Batteries, x4

  Total items: 4
  ```

### US-007: Admin sets household primary store and store list
**Description:** As the admin, I want to define the household's known stores so the skill has defaults and can match items correctly.

**Acceptance Criteria:**
- [ ] Any user can say "Add store [name]" or "Add store [name] at [address]" to register a store
- [ ] If web search is available, skill searches for the store's address and presents the result: "Found: Whole Foods — 123 Main St, Anytown. Is this the right location? (yes / enter correct address)"
- [ ] If user confirms, that address is saved; if user provides a different address, the user-provided address is saved
- [ ] If web search is unavailable and no address was provided, skill prompts: "What's the address for [store]?"
- [ ] Confirmed store is written to `config.json`
- [ ] Admin can designate one store as primary: "Set [store] as primary store"
- [ ] Admin can set fallback order: "Fallback order: Whole Foods → Costco → Target"
- [ ] Registered stores are used as options when asking the user which store for a new item

### US-008: Skill assigns item to store by category when store is unknown
**Description:** As a user, I want items I add without specifying a store to automatically go to the right place.

**Acceptance Criteria:**
- [ ] Skill maintains a category→store mapping in `config.json` (e.g., produce → farmers market, bulk → Costco)
- [ ] Admin can update category mappings: "Assign produce to [store]"
- [ ] When user doesn't specify a store for an item, skill checks category mapping first, then falls back to primary store
- [ ] Skill tells the user what assignment was made: "Added to Whole Foods (produce category default)"

---

## Functional Requirements

- FR-1: All shared data lives under a user-specified local path, initialized by admin on first run
- FR-2: `config.json` stores: shared path, primary store, store list (name + address), fallback order, category→store mappings
- FR-3: `users.md` stores: name, role (admin/member), date added — one record per user
- FR-4: `list.md` stores current items grouped by store; each entry: item, qty, store, added-by, timestamp
- FR-5: `history.md` logs all additions and removals with user, timestamp, action
- FR-6: User identity is resolved from OpenClaw memory on every invocation; name is persisted to OpenClaw memory on first use
- FR-7: Every write to `list.md` includes the resolved user name and timestamp
- FR-7: When adding an item, skill always resolves the store before writing (via user input → category default → primary store, in that order)
- FR-8: When web search tool is available, skill searches for item availability at the target store before confirming
- FR-9: Store headings in list output always show full name + address
- FR-10: Only admin can add users, set primary store, set fallback order, or modify category mappings; any user can add new stores
- FR-11: Any user on the `users.md` list has full read/write access to the grocery list
- FR-12: Before adding any item, skill checks for duplicates (case-insensitive, fuzzy match) and prompts user to merge or confirm
- FR-13: Duplicate merges are logged to `history.md` with both users' names
- FR-14: History is surfaced on request (e.g. "what changed recently?") — not proactively pushed
- FR-15: When a new store is added, skill web-searches for its address, presents the result for user confirmation, and falls back to prompting for the address if search is unavailable or user rejects the result

---

## Non-Goals

- No real-time push notifications when the list changes (users see changes on next read)
- No mobile app or UI — purely an OpenClaw skill interaction
- No meal planning — this skill handles what to buy, not what to cook
- No receipt scanning or barcode support
- No price tracking or budget management
- No automatic item reordering or smart replenishment
- No integration with external grocery APIs or ordering systems

---

## Data File Structure

```
[shared-path]/
├── config.json        # Stores, categories, primary store, fallback order
├── users.md           # Family members and roles
├── list.md            # Current grocery list, grouped by store
└── history.md         # Log of all adds/removes
```

### config.json schema
```json
{
  "primary_store": "Whole Foods",
  "stores": [
    { "name": "Whole Foods", "address": "123 Main St, Anytown" },
    { "name": "Costco", "address": "456 Oak Ave, Anytown" }
  ],
  "fallback_order": ["Whole Foods", "Costco", "Target"],
  "category_store_map": {
    "produce": "Whole Foods",
    "bulk": "Costco",
    "electronics": "Target"
  }
}
```

---

## Technical Considerations

- Shared path is the single source of truth; all agents read/write the same files
- No locking mechanism required for v1 — concurrent edits are rare in a family context
- Web search is optional; skill degrades gracefully when unavailable
- Skill should read `config.json` and `users.md` on every invocation to pick up changes made by other agents
- User identity is provided by the user at the start of each session (not auto-detected)

---

## Success Metrics

- Any family member can add an item and it is immediately visible to all others via "show list"
- Items are correctly categorized to the right store ≥ 90% of the time without user correction
- Admin can add a new family member in under 2 conversational turns
- List output is always grouped by store with address, zero unformatted dumps

---

## Open Questions

None.
