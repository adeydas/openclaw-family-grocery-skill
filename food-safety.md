---
topic: Food Safety
skill: Family Grocery
---

# Food Safety — Family Grocery

Tracks known safety risks and safer alternatives per grocery item. Any family member can add, edit, or remove risks. Safety entries are surfaced in the grocery list view.

Data lives in `[shared-path]/safety.json`.

---

## Add Safety Risk

**Triggers:** "Add safety risk for [item]", "Flag [item] as risky", "[item] has a safety concern", "Mark [item] unsafe"

**Flow:**
1. Parse `item` and `risk description` from user input. If either is missing, ask.
2. Read `safety.json`. Fuzzy-match `item` (case-insensitive, singular/plural) against existing entries.
   - If a match exists → "A safety risk for [item] already exists: [risk]. Would you like to edit it instead?"
3. Ask: "Any safer alternatives? (comma-separated, or 'none')"
4. Build entry:
   ```json
   {
     "item": "[normalized item name]",
     "risk": "[risk description]",
     "alternatives": ["[alt1]", "[alt2]"],
     "added_by": "[current user]",
     "added_on": "[YYYY-MM-DD]",
     "updated_by": null,
     "updated_on": null
   }
   ```
   Use an empty array `[]` if the user said "none" or skipped.
5. Append to `safety.json` → `risks` array. Write file.
6. Confirm: "Safety risk added for [item]: [risk]. Alternatives: [list, or 'none']."

---

## Edit Safety Risk

**Triggers:** "Update safety risk for [item]", "Edit [item] risk", "Change the alternative for [item]", "Update [item] safety note"

**Flow:**
1. Read `safety.json`. Fuzzy-match `item`. If no match → "No safety risk on file for [item]."
2. Display current entry:
   ```
   Current safety note for [item]:
   Risk: [risk]
   Alternatives: [list or 'none']
   ```
3. Ask: "What would you like to update? (risk description / alternatives / both)"
4. For each field being updated, ask for the new value.
5. Apply changes. Set `updated_by` to current user and `updated_on` to today's ISO date.
6. Write file.
7. Confirm: "Safety risk for [item] updated."

---

## Remove Safety Risk

**Triggers:** "Remove safety risk for [item]", "Clear [item] safety flag", "Delete [item] risk", "Remove [item] warning"

**Flow:**
1. Read `safety.json`. Fuzzy-match `item`. If no match → "No safety risk on file for [item]."
2. Confirm: "Remove the safety risk for [item]? (yes/no)"
3. On yes: remove the entry from `risks` array. Write file.
4. Confirm: "Safety risk for [item] removed."

---

## List All Safety Risks

**Triggers:** "Show safety risks", "List all food safety notes", "What items have safety warnings?", "Show food safety"

**Flow:**
1. Read `safety.json`.
2. If `risks` is empty → "No food safety risks on file."
3. Otherwise display:

```
Food safety notes:
• [Item] — [Risk]. Alternatives: [alt1], [alt2].
• [Item] — [Risk]. No alternatives on file.
```

List all entries regardless of whether the item is currently on the grocery list.

---

## safety.json Format

```json
{
  "risks": [
    {
      "item": "raw chicken",
      "risk": "Salmonella contamination — keep refrigerated, cook to 165°F internal temp",
      "alternatives": ["pre-cooked rotisserie chicken", "tofu"],
      "added_by": "Abhishek",
      "added_on": "2026-03-28",
      "updated_by": null,
      "updated_on": null
    }
  ]
}
```

- `item`: normalized lowercase item name
- `risk`: free-text description of the safety concern
- `alternatives`: array of safer substitutes; empty array if none provided
- `added_by` / `added_on`: attribution at creation
- `updated_by` / `updated_on`: attribution at last edit; null until edited
