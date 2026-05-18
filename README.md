# Family Grocery

A grocery list skill for [OpenClaw](https://openclaw.com). Add, remove, and view grocery items organized by store — with web-verified addresses and item availability.

**Install from ClawHub:** [clawhub.ai/adeydas/family-grocery](https://clawhub.ai/adeydas/family-grocery)

## Features

- **Store-aware** — items are organized by store with address and hours
- **Smart store assignment** — items auto-assigned by saved item mapping or category, otherwise added to `Unassigned` until mapped
- **Image input** — you can send a photo of a grocery item and the skill will use vision to identify and add it
- **Duplicate detection** — fuzzy matching prevents double entries
- **Web search integration** — verifies store addresses, hours, and item availability (optional, degrades gracefully)
- **Change history** — every add, remove, and merge is logged and surfaceable on request
- **Item timestamps** — every grocery item is stored with its add timestamp and shown with that timestamp in list views
- **Food safety** — track safety risks and safer alternatives per item; surfaced automatically when viewing the list
- **Health notices** — checks [Canada public health notices](https://www.canada.ca/en/public-health/services/public-health-notices.html) for active outbreaks when adding items; warnings surfaced on add and in list view

## How It Works

```
[shared-path]/
├── config.json    # Stores, primary store, fallback order, item→store map, category→store map
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
"Add pistachios"
```

You can also send a photo of an item with a message like:
```
"Add this"
```

The skill will identify the item from the image, extract details like variant and size when visible, and then add it through the normal mapping flow.

If the item has no saved item mapping and no category mapping:
```
Added pistachios (1) to Unassigned on 2026-05-18.
Pistachios is currently unassigned and should be mapped to a store.
```

If the item was identified from an image:
```
Identified from image: 2% milk (2L).
Added 2% milk (2L) to Whole Foods on 2026-05-18.
```

If a Canada public health notice is active for the item:
```
Added pistachios (1) to Whole Foods.
⚠️ Health notice: Pistachios are linked to an active Salmonella outbreak — Do not consume recalled pistachios due to possible Salmonella contamination. See: https://www.canada.ca/en/public-health/services/public-health-notices/2025/outbreak-salmonella-infections-pistachios-related-products.html
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
- Milk, 2L — added on 2026-03-10
- Eggs, x12 — added on 2026-03-11

🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm
- Olive oil, 3L — added on 2026-03-09

Total items: 3

⚠️ Safety notes:
- Raw chicken — Salmonella contamination. Alternatives: rotisserie chicken, tofu.
- Pistachios — Active health notice: Salmonella outbreak linked to pistachios. See: https://www.canada.ca/en/public-health/services/public-health-notices/2025/outbreak-salmonella-infections-pistachios-related-products.html
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
| `health-notices.md` | Canada public health notices — active outbreak checks and warnings |
| `memory-template.md` | Data file templates and OpenClaw memory keys |

## License

MIT
