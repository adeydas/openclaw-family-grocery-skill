---
topic: Health Notices
skill: Family Grocery
---

# Health Notices — Family Grocery

Checks Canada public health notices for active outbreaks related to grocery items. Warnings are surfaced when adding an item and when viewing the list.

Source: [Canada Public Health Notices](https://www.canada.ca/en/public-health/services/public-health-notices.html)

---

## When the Check Runs

- **On item add** — after resolving the store, before writing to `list.md`
- **On list view** — as part of the safety notices section (see `lists.md`)

---

## Check Flow

1. **Fetch the notices page** — `https://www.canada.ca/en/public-health/services/public-health-notices.html`
2. **Extract active outbreak investigations** — parse the "Active outbreak investigations" section for notice titles and their links.
3. **Fuzzy-match the item** — compare the item name (case-insensitive, singular/plural) against each active notice title. For example, "pistachios" matches a notice titled "Outbreak of Salmonella infections linked to various brands of pistachios and pistachio-containing products".
4. **If no match** — no warning. Proceed normally.
5. **If a match is found** — follow the notice link and extract:
   - **Risk summary** — the "At a glance" section (first 1–2 sentences)
   - **Advice** — the "How to protect your health" section (first 1–2 key points)
   - **Notice URL** — the full link to the notice page
6. **Show warning** (see format below).

---

## Warning Format

### On item add
After the add confirmation, append:

```
⚠️ Health notice: [Item] is linked to an active public health outbreak — [Risk summary]. [Key advice point]. See: [URL]
```

Example:
```
⚠️ Health notice: Pistachios are linked to an active Salmonella outbreak — Do not consume recalled pistachios and pistachio-containing products due to possible Salmonella contamination. Check recall listings to see if your product is affected. See: https://www.canada.ca/en/public-health/services/public-health-notices/2025/outbreak-salmonella-infections-pistachios-related-products.html
```

### On list view
In the existing "⚠️ Safety notes" section, append health notice matches after the `safety.json` entries:

```
⚠️ Safety notes:
• [Item] — [Risk from safety.json]. Alternatives: [alt1], [alt2].
• [Item] — Active health notice: [Risk summary]. See: [URL]
```

If no `safety.json` matches exist but a health notice match does, use the "⚠️ Safety notes" heading with just the health notice entries.

---

## Graceful Degradation

- If web fetch is unavailable → skip the health notice check silently. Do not block the add operation.
- If the notices page is unreachable or returns an error → skip silently. Proceed with the add.
- If a notice link is broken → show the warning with the title only and omit the detailed summary.
- Never retry or prompt the user when the check fails — just proceed without it.

---

## Matching Rules

- Match item names against notice titles using fuzzy matching (case-insensitive, singular/plural)
- Match against the full notice title, not just keywords — this avoids false positives (e.g., "chicken" should not match a "chickenpox" notice)
- If an item matches multiple active notices, show all of them
- The match should cover both direct product names (e.g., "pistachios") and products commonly containing the item (e.g., "pistachio-containing products")

---

## URL Reference

| Resource | URL |
|----------|-----|
| Active public health notices | `https://www.canada.ca/en/public-health/services/public-health-notices.html` |
| Closed outbreak archive | `https://www.canada.ca/en/public-health/services/public-health-notices/archive.html` |
| Recalls and safety alerts | `https://recalls-rappels.canada.ca/en` |

Only check **active** notices. Do not check the closed outbreak archive.
