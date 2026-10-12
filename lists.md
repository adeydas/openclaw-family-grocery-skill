# List Operations — Family Grocery

All live list/history operations use the installed `family-grocery` CLI. Here `[cli]` is the saved absolute `family_grocery_cli` path and `[path]` is `family_grocery_path`; substitute safely quoted arguments. `list.md`/`history.md` are legacy import/export artifacts, never fallback writable state.

## CLI Contract

```text
[cli] --data-dir [path] list
[cli] --data-dir [path] add --name [item] --quantity [qty] --store [store] --expected-revision [revision] --operation-id [uuid]
[cli] --data-dir [path] update --id [id] --version [version] --quantity [replacement-qty] --action MERGE --operation-id [uuid]
[cli] --data-dir [path] update --id [id] --version [version] --quantity [replacement-qty] --action UPDATE --operation-id [uuid]
[cli] --data-dir [path] remove --id [id] --version [version] --operation-id [uuid]
[cli] --data-dir [path] history
[cli] --data-dir [path] link --base-url [public-url]
```

`update` also accepts `--name` and `--store`. Output is JSON; failure returns nonzero and a structured error on stderr. Although the CLI can generate an operation ID for manual use, an agent must create its UUID **before** launching each mutation and retain it until the outcome is known.

A snapshot has `{items, revision, server_time}`. Each item has `{id, name, quantity, store, added_on, version}`; new items use an ISO UTC `added_on` timestamp, while imported date-only values retain their original ISO calendar date. Adds/updates return `{item, revision, operation_id}`. Removes return `{removed, id, revision, operation_id}`. `removed: false` means the same entry was already removed, with no second history event. Re-adding the same name creates a different ID.

### Concurrency and uncertain outcomes

Each successful mutation commits item, history, revision, and retry receipt in one SQLite transaction. CLI and browser writers share this mechanism.

- **Timeout/interruption/missing response:** retry identical arguments with the same operation ID. Never make a new ID solely because a response was lost.
- **`revision_conflict`:** reload the list, repeat the fuzzy duplicate decision, and reassess the add. Use a new operation ID if making a revised request.
- **`item_conflict`:** reload that exact item and reassess its changed name/quantity/store. Seek a renewed user choice if the change affects their intention; do not blindly check off a new version they have not seen.
- **`not_found` on update:** the entry is gone; do not implicitly recreate it. If absent during removal, report that it is already off the list.
- **`operation_conflict`:** the ID was used with different arguments. Reconcile the earlier outcome before proceeding; do not automatically submit the same intention under another ID.

Two people removing different items both succeed. Two people removing the same item create one removal/history record. An old checkbox cannot remove a replacement entry. Do not add household identity to commands or history.

## Adding an Item

1. **Parse input:** “Add milk” → quantity `1`; “Add 2L of milk” → `2L`; “Add a dozen eggs” → `x12`. For an image use vision for the item, variant, and visible package size. For approximation say `Identified from image: [item] ([qty]) (best match).`
2. **Read a fresh CLI list and check duplicates:** fuzzy-match case-insensitively, including simple descriptors and singular/plural. If matched, ask `[Item] ([qty]) was already added on [Mon DD]. Add more, update quantity, or cancel?`
3. **Resolve the duplicate choice:** “add more” computes the replacement (e.g. `x12` + `x6` → `x18`) and calls `update --action MERGE` on that ID/version; “update to X” uses `UPDATE`; “cancel” changes nothing. Do not guess arithmetic across incompatible units. Add a separate entry only on an explicit choice, using snapshot revision.
4. **Resolve a new entry's store:** explicit user choice → fresh config's fuzzy item mapping → category mapping → `Unassigned`. Say `Adding to [store] (saved item mapping).` or `Adding to [store] ([category] category default).` when inferred. Normalize reusable mappings so milk can match `2% milk` and `1% milk`.
5. **Check availability if possible:** for assigned stores search `[item] available at [store] [address]`. Say `Confirmed available at [store].` only with supporting evidence; otherwise `Couldn't confirm availability at [store] — adding anyway.` Skip Unassigned. Note unavailable search once and proceed.
6. **Ask about missing fallbacks:** `Any fallback stores for items from [store]? (e.g. if they're out of stock)` when appropriate. Save the answer through the shared JSON lock/atomic replacement, preserving unrelated changes.
7. **Submit:** create an operation UUID and call `add` with name/quantity/store and the revision used for the duplicate decision. Reassess conflicts as above. Do not write a Markdown row or append history.
8. **Learn explicit store choices:** after success, save the normalized item mapping with the metadata lock. If that save fails, explain it without repeating the already-successful add. Confirm the preference only after its save succeeds.
9. **Confirm:** use the returned item's date: `Added [item] ([qty]) to [store] on [YYYY-MM-DD].` Prepend image identification when relevant. Append `I'll remember that [normalized item] goes to [store] next time.` for a saved mapping. For Unassigned append `[Item] is currently unassigned and should be mapped to a store.`
10. **Check health notices** following [health-notices.md](health-notices.md), then append matches. A fetch failure does not block or roll back the grocery operation. After a successful complete check, read a fresh full list and rebuild its matched notices, using exact current item names. Never overwrite the cache with only the newly added item's matches; retain known warnings on failure.

## Removing an Item

Triggers: “Remove [item]”, “I got the [item]”, “Delete [item]”, “Cross off [item]”.

1. Read `list` and fuzzy-match current entries. If absent, say `I don't see [item] on the list.`
2. For ambiguity across stores, ask `I see [item] at [store A] and [store B]. Remove from which? (both / [store A] / [store B])`. Disambiguate separately listed same-name entries at one store too.
3. Generate an operation UUID for each intended entry, then call `remove` with its exact ID/version. Follow retry/conflict rules. Bulk removal is a sequence of atomic operations, so report any partial outcome accurately.
4. Confirm `[Item] removed from [store].` If `removed: false`, say it was already checked off. The service creates history; do not append another entry.

The mobile checkbox uses the same storage rules: a stale version requires another decision after refreshing, a failed save keeps the row, and simultaneous checks are idempotent.

## Viewing the List

Triggers: “Show me the grocery list”, “What do we need?”, “Show the list”.

1. Read CLI `list` and fresh metadata. Match `safety.json`, check health notices, and update the optional cache following [health-notices.md](health-notices.md).
2. Run `link --base-url [family_grocery_public_url]`, which returns `url`, `link_id`, `created_at`, `expires_at`, and `reused`.
3. Return the exact URL, snapshot count, and actual expiry in the user's known timezone (or explicitly UTC). Deliver this private link only through the authorized conversation.

```text
Open grocery checklist — [count] items:
[url]
Expires [date/time and timezone]. Close expires this link for everyone.
```

Everyone sees the same household list. The link expires four hours after creation; repeated requests reuse it with no renewal. Opening, sharing, or refreshing does not extend it. Close revokes all sessions using that link; merely closing the browser tab does not. The next request after Close/expiry creates a new link. Saved groceries/history persist.

Return a link for an empty list too, with `0 items` and `The grocery list is empty.` If the service is known to be unavailable, explain that and provide current text from the CLI. Do not substitute legacy files, manufacture links, or count a minted token as deployment-health evidence.

### Text views and metadata

For a store-specific request, return the shared mobile link and tell the user to select that store's filter on the page. Use text only when explicitly requested or as a service fallback. Group stores alphabetically, Unassigned last; show known address/hours, quantity, and add date for every row:

```text
🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm, Sun 10am–6pm
- Olive oil, 3L — added on 2026-03-09

🏪 Whole Foods (123 Main St, Anytown) — Mon–Sat 8am–9pm, Sun 9am–7pm
- Milk, 2L — added on 2026-03-10
- Eggs, x12 — added on 2026-03-11

📋 Unassigned
- Batteries, x4 — added on 2026-03-12

Total items: 4
```

Label filtered totals. Omit unknown hours; use `address not on file` instead of inventing an address. For missing hours, search `[store] [address] store hours`, present findings for confirmation, and save confirmed data under the metadata lock. If search is unavailable, ask for hours or allow “skip”. Never withhold a working mobile link while resolving optional hours. If offering a link alongside filtered text, explain that it opens the entire shared list.

### Safety notes

Fuzzy-match current items against fresh saved risks and available health notices. Append one section after the link/text only for matches:

```text
⚠️ Safety notes:
• [Item] — [Risk]. Alternatives: [alt1], [alt2].
• [Item] — [Risk]. No alternatives on file.
• [Item] — Active health notice: [Risk summary]. See: [URL]
```

The webpage displays saved risks and cached notices; it does not fetch live health data. Failed refreshes preserve the old `checked_at`; identify cached warnings by that time rather than implying fresh verification.

## Viewing History

Run `history` for “What changed recently?” or “Show history”. Filter events by timestamp/action as requested and describe actual changes without personal attribution:

- `Added eggs (x12) on Mar 10.`
- `Removed milk from Costco on Mar 11.`
- `Updated eggs from x12 to x18 on Mar 12.`

New UPDATE/MERGE events retain `before` and `after` item objects as JSON in `details`. Use those values for the real change. Legacy events preserve the item description in `details`, including merge arithmetic when present. Never invent a delta or member identity.

## Exports and Backups

```text
[cli] --data-dir [path] export --output-dir [new-export-directory]
[cli] --data-dir [path] backup --output [new-backup-file.sqlite3]
```

Exports are readable snapshots, not writable synchronization. The destination must differ from live state and contain no existing `list.md`/`history.md`. Backups use SQLite's backup API, refuse existing destinations, and include private credentials. Back up JSON separately as described in [the VPS guide](docs/vps-setup.md). Never copy only a live SQLite main file while ignoring its WAL.
