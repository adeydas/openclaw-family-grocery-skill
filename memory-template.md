# Data File Templates — Family Grocery

These files are created in `[shared-path]/` during initialization.

---

## config.json

```json
{
  "primary_store": "",
  "stores": [],
  "fallback_order": [],
  "item_store_map": {},
  "category_store_map": {}
}
```

---

## list.md

```markdown
# Grocery List

<!-- Items are grouped by store. Each section uses ## [Store Name] as heading. -->
<!-- Unassigned items go under ## Unassigned at the bottom. -->
```

---

## history.md

```markdown
# Grocery History

<!-- Format: YYYY-MM-DD HH:MM | ACTION | item (qty) | store -->
<!-- Actions: ADD, REMOVE, MERGE, UPDATE -->
```

---

## safety.json

```json
{
  "risks": []
}
```

---

## OpenClaw Memory Keys

These keys are saved per-agent (not in the shared path):

| Key | Value | Set when |
|-----|-------|----------|
| `family_grocery_path` | Path (e.g. "/Users/Shared/grocery") | First-time setup |

The path is saved during initialization and reused on every invocation.
