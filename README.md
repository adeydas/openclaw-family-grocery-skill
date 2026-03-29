# Family Grocery

A shared family grocery list skill for [OpenClaw](https://openclaw.com). Multiple family members can add, remove, and view grocery items through their own agents — all backed by a single shared data folder.

**Install from ClawHub:** [clawhub.ai/adeydas/family-grocery](https://clawhub.ai/adeydas/family-grocery)

## Features

- **Shared list** — one grocery list the whole family contributes to
- **Store-aware** — items are organized by store with address and hours
- **Smart store assignment** — items auto-assigned to stores by category, with manual override
- **Duplicate detection** — fuzzy matching prevents double entries across family members
- **Web search integration** — verifies store addresses, hours, and item availability (optional, degrades gracefully)
- **Access control** — admin manages family members; all approved members get full list access
- **Change history** — every add, remove, and merge is logged and surfaceable on request
- **Food safety** — track safety risks and safer alternatives per item; surfaced automatically when viewing the list

## How It Works

```
[shared-path]/
├── config.json    # Stores, primary store, fallback order, category→store map
├── users.md       # Family members and roles (admin/member)
├── list.md        # Current grocery list, grouped by store
├── history.md     # Log of all adds, removes, and merges
└── safety.json    # Food safety risks and alternatives per item
```

All agents read and write to the same shared local path. The admin sets it up once, adds family members by name, and shares the path.

## Setup

### 1. Admin initializes

The first user becomes the admin. The skill will ask for a shared path (e.g. `/Users/Shared/grocery`), create the directory, and initialize the data files.

### 2. Admin adds family members

```
"Add user Nita"
```

### 3. Members connect

Each member's agent needs:
- Their name stored in OpenClaw memory (`family_grocery_user`)
- The shared path stored in OpenClaw memory (`family_grocery_path`)

```
"Connect to family grocery at /Users/Shared/grocery"
```

## Usage

**Add items:**
```
"Add 2L of milk"
"Add eggs at Costco"
"Add ingredients for carbonara"
```

**Remove items:**
```
"Remove the milk"
"I got the eggs"
```

**View list:**
```
"Show me the grocery list"
```

Output:
```
🏪 Whole Foods (123 Main St, Anytown) — Mon–Sat 8am–9pm, Sun 9am–7pm
- Milk, 2L
- Eggs, x12

🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm
- Olive oil, 3L

Total items: 3

⚠️ Safety notes:
- Raw chicken — Salmonella contamination. Alternatives: rotisserie chicken, tofu.
```

**Manage stores:**
```
"Add store Whole Foods"
"Set Whole Foods as primary store"
"Assign produce to Whole Foods"
```

**View history:**
```
"What changed recently?"
```

**Food safety:**
```
"Add safety risk for raw chicken"
"Update the alternative for raw chicken"
"Show safety risks"
"Remove safety risk for raw chicken"
```

## Skill Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill definition — startup sequence, core rules, scope |
| `lists.md` | Add, remove, view, and history operations |
| `stores.md` | Store management — add, primary, fallback, categories |
| `user-management.md` | Admin setup, add/remove users |
| `food-safety.md` | Food safety risks and alternatives — add, edit, remove, list |
| `memory-template.md` | Data file templates and OpenClaw memory keys |

## License

MIT
