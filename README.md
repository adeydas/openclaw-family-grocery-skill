# Family Grocery

A grocery list skill for [OpenClaw](https://openclaw.com). Add, remove, and view grocery items organized by store — with web-verified addresses and item availability.

**Install from ClawHub:** [clawhub.ai/adeydas/family-grocery](https://clawhub.ai/adeydas/family-grocery)

## Features

- **Store-aware** — items are organized by store with address and hours
- **Smart store assignment** — items auto-assigned to stores by category, with manual override
- **Duplicate detection** — fuzzy matching prevents double entries
- **Web search integration** — verifies store addresses, hours, and item availability (optional, degrades gracefully)
- **Change history** — every add, remove, and merge is logged and surfaceable on request
- **Food safety** — track safety risks and safer alternatives per item; surfaced automatically when viewing the list

## How It Works

```
[shared-path]/
├── config.json    # Stores, primary store, fallback order, category→store map
├── list.md        # Current grocery list, grouped by store
├── history.md     # Log of all adds, removes, and merges
└── safety.json    # Food safety risks and alternatives per item
```

Data lives at a local path you choose during setup.

## Setup

The skill will ask for a data path (e.g. `/Users/Shared/grocery`), create the directory, and initialize the data files.

```
"What path should I use for the grocery data?"
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
| `food-safety.md` | Food safety risks and alternatives — add, edit, remove, list |
| `memory-template.md` | Data file templates and OpenClaw memory keys |

## License

MIT
