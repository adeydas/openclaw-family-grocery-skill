# Data and Memory — Family Grocery

The installed CLI creates `grocery.sqlite3` and missing `config.json`/`safety.json` during `init`. Existing JSON and legacy Markdown are preserved. SQLite owns the live list/history; never create new live Markdown templates or edit imported originals after migration.

## OpenClaw Memory Keys

Save these per-agent settings after verifying deployment:

| Key | Example | Purpose |
| --- | --- | --- |
| `family_grocery_cli` | `/opt/family-grocery/.venv/bin/family-grocery` | Absolute installed executable |
| `family_grocery_path` | `/var/lib/family-grocery` | Shared authoritative state directory |
| `family_grocery_public_url` | `https://hadol.deydas.com/grocery/` | Base URL passed to `link --base-url` |

Reuse established values. Do not save expiring private links as permanent configuration. No household username or attribution key is required.

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

Store rows use `{ "name": "Costco", "address": "Full address", "hours": "Confirmed hours" }`. Preserve unknown keys in narrow changes. See [stores.md](stores.md) for preferences and mappings.

## safety.json

```json
{
  "risks": []
}
```

Risk rows use `{ "item": "item name", "risk": "user-maintained note", "alternatives": ["alternative"] }`. Preserve existing extra fields such as timestamps. See [food-safety.md](food-safety.md).

## health-notices.json

Optional: the web service reads but never fetches/updates this cache. After a **successful complete check**, read a fresh full grocery list, fuzzy-match every current item against active notices, and atomically replace the complete set of matches:

```json
{
  "checked_at": "2026-10-12T16:30:00Z",
  "notices": [
    {
      "item": "exact current grocery item name",
      "risk": "summary supported by the notice",
      "url": "https://www.canada.ca/en/public-health/services/public-health-notices.html"
    }
  ]
}
```

Use the actual UTC check timestamp and a specific official notice URL when available. The cache's `item` must equal the current grocery item's name exactly; the webpage uses exact matching for these agent-resolved notices. Cache all matches for the complete current list, not only matches for the last added item. A verified successful check with no matches writes `notices: []`. Failed, partial, or unavailable fetches leave the previous file and `checked_at` unchanged. Missing cache means no cached check, not “no active notices”. See [health-notices.md](health-notices.md).

## Concurrent Metadata Updates

Every agent write to `config.json`, `safety.json`, or `health-notices.json` must use the shared `[shared-path]/metadata.lock`. Hold exclusive `fcntl.flock` **from the fresh read through atomic replacement**. This prevents lost changes; atomic rename lets the web service read complete JSON without taking the lock.

Use this procedure on Linux/macOS with the private shared Unix group configured in [the VPS guide](docs/vps-setup.md):

```python
import fcntl
import json
import os
from pathlib import Path
import tempfile

def update_metadata(data_dir, filename, change, default):
    if filename not in {"config.json", "safety.json", "health-notices.json"}:
        raise ValueError("Unsupported metadata filename")
    directory = Path(data_dir)
    lock_fd = os.open(directory / "metadata.lock", os.O_CREAT | os.O_RDWR, 0o660)
    with os.fdopen(lock_fd, "a+") as lock:
        if os.fstat(lock.fileno()).st_uid == os.geteuid():
            os.fchmod(lock.fileno(), 0o660)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / filename
        # Read after locking. Never silently replace malformed JSON by defaults.
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        updated = change(current)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{filename}.", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o660)
                json.dump(updated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
```

`change` applies the intended narrow edit to the freshly loaded object, preserves unrelated keys/rows, and returns it. A successful health refresh replaces `checked_at` and the full `notices` list. Complete external lookups/user confirmation before locking; never hold the lock while browsing or waiting. All writers must follow this protocol; direct file writes are unsafe in a shared installation.

The dedicated service/OpenClaw group owns the private setgid data directory (`2770`) and metadata (`0660`). The same group must own replacement files. Never grant world access to fix permissions.
