"""Transactional grocery storage and revocable shared-link authentication.

All writers (including the local CLI) use this module. A write lock covers the
authorization check, revision check, item change, history, and retry receipt.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid


LINK_TTL = 4 * 60 * 60
DEFAULT_CONFIG = {
    "primary_store": "", "stores": [], "fallback_order": [],
    "item_store_map": {}, "category_store_map": {},
}


class GroceryError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _text(value, field, limit=500):
    if not isinstance(value, str) or not value.strip():
        raise GroceryError("invalid_input", f"{field} must be nonempty text.")
    value = value.strip()
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise GroceryError("invalid_input", f"{field} is too long or contains control characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GroceryError("invalid_input", f"{field} contains invalid Unicode.") from exc
    return value


def _integer(value, field):
    if type(value) is not int or value < 0:
        raise GroceryError("invalid_input", f"{field} must be a nonnegative integer.")
    return value


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _legacy_time(value, path, line, preserve_date=False):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if preserve_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.date().isoformat()
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError as exc:
        raise GroceryError("migration_error", f"{path.name}:{line}: invalid timestamp {value!r}.") from exc


def _legacy_lines(path):
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GroceryError("migration_error", f"Cannot read {path.name}: {exc}") from exc
    # Preserve line numbers while removing template comments, including multiline ones.
    content = re.sub(r"<!--[\s\S]*?-->", lambda m: "\n" * m.group().count("\n"), content)
    return [(n, line.strip()) for n, line in enumerate(content.splitlines(), 1) if line.strip()]


def _legacy_list(path):
    items, store = [], None
    pattern = re.compile(r"^- (.+) \((.+)\) — added (?:by .+ )?on (\S+)$")
    for number, line in _legacy_lines(path):
        if line == "# Grocery List":
            continue
        if line.startswith("## "):
            store = _text(line[3:], "store", 200)
            continue
        match = pattern.fullmatch(line)
        if match and store:
            name, quantity, added = match.groups()
            items.append({"id": str(uuid.uuid4()), "name": _text(name, "name"),
                          "quantity": _text(quantity, "quantity", 100), "store": store,
                          "added_on": _legacy_time(added, path, number, preserve_date=True), "version": 1})
            continue
        raise GroceryError("migration_error", f"{path.name}:{number}: unsupported row; originals were not changed: {line}")
    return items


def _legacy_history(path):
    entries = []
    pipe = re.compile(r"^(?:- )?(\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)?)?)\s*\|\s*(ADD|REMOVE|MERGE|UPDATE)\s*\|\s*(.+?)\s*\|\s*([^|]+?)(?:\s*\|\s*by .+)?$")
    removal = re.compile(r"^(?:- )?\[?(\d{4}-\d\d-\d\d[ T]\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)?)\]? REMOVE: (.+) from (.+?)(?: — by .+)?$")
    for number, line in _legacy_lines(path):
        if line == "# Grocery History":
            continue
        match = pipe.fullmatch(line)
        if match:
            timestamp, action, detail, store = match.groups()
        else:
            match = removal.fullmatch(line)
            if not match:
                raise GroceryError("migration_error", f"{path.name}:{number}: unsupported history row; originals were not changed: {line}")
            timestamp, detail, store = match.groups()
            action = "REMOVE"
        item = re.fullmatch(r"(.+) \((.+)\)", detail)
        name, quantity = item.groups() if item else (detail, "")
        entries.append({"timestamp": _legacy_time(timestamp, path, number), "action": action,
                        "name": name, "quantity": quantity, "store": store.strip(), "details": detail})
    return entries


class Store:
    def __init__(self, data_dir, clock=time.time):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.db_path = self.data_dir / "grocery.sqlite3"
        self.clock = clock

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=20, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 20000")
        return conn

    @contextmanager
    def _transaction(self, write=False):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, import_legacy=True):
        self.data_dir.mkdir(mode=0o2770, parents=True, exist_ok=True)
        # Pre-create restrictively: sqlite's ordinary create mode otherwise depends on umask.
        fd = os.open(str(self.db_path), os.O_CREAT | os.O_RDWR, 0o660)
        os.close(fd)
        # The deployment's private setgid directory shares this only with the
        # dedicated service/OpenClaw Unix group. Never grant world access.
        db_stat = self.db_path.stat()
        if db_stat.st_uid == os.geteuid():
            os.chmod(self.db_path, 0o660)
        elif db_stat.st_mode & 0o007:
            raise GroceryError("permissions_error", "The database has world permissions. Ask its owner to restrict it to the trusted grocery group (0660) before initialization.")
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        finally:
            conn.close()
        schema = [
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, name TEXT NOT NULL, quantity TEXT NOT NULL, store TEXT NOT NULL, added_on TEXT NOT NULL, version INTEGER NOT NULL, removed_at TEXT)",
            "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, action TEXT NOT NULL, item_id TEXT, name TEXT NOT NULL, quantity TEXT NOT NULL, store TEXT NOT NULL, details TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS links (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL)",
            "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, link_id TEXT NOT NULL REFERENCES links(id))",
        ]
        with self._transaction(write=True) as conn:
            for statement in schema:
                conn.execute(statement)
            conn.execute("INSERT OR IGNORE INTO metadata VALUES ('revision', '0')")
            conn.execute("INSERT OR IGNORE INTO metadata VALUES ('signing_key', ?)", (secrets.token_hex(32),))
            marker = conn.execute("SELECT value FROM metadata WHERE key = 'legacy_import'").fetchone()
            if marker:
                summary = {"initialized": True, "already_initialized": True, "migration": json.loads(marker[0])}
            else:
                items = _legacy_list(self.data_dir / "list.md") if import_legacy else []
                entries = _legacy_history(self.data_dir / "history.md") if import_legacy else []
                for item in items:
                    conn.execute("INSERT INTO items (id,name,quantity,store,added_on,version) VALUES (:id,:name,:quantity,:store,:added_on,:version)", item)
                for entry in entries:
                    conn.execute("INSERT INTO history (timestamp,action,name,quantity,store,details) VALUES (:timestamp,:action,:name,:quantity,:store,:details)", entry)
                if items:
                    self._bump(conn)
                migration = {"items": len(items), "history": len(entries), "skipped": not import_legacy,
                             "legacy_timestamps_without_timezone": "date-only item dates preserved; timestamps with time interpreted as UTC; originals preserved"}
                conn.execute("INSERT INTO metadata VALUES ('legacy_import', ?)", (json.dumps(migration),))
                summary = {"initialized": True, "already_initialized": False, "migration": migration}
        for filename, content in (("config.json", DEFAULT_CONFIG), ("safety.json", {"risks": []})):
            try:
                fd = os.open(str(self.data_dir / filename), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(content, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        return summary

    @staticmethod
    def _revision(conn):
        return int(conn.execute("SELECT value FROM metadata WHERE key = 'revision'").fetchone()[0])

    def _bump(self, conn):
        revision = self._revision(conn) + 1
        conn.execute("UPDATE metadata SET value = ? WHERE key = 'revision'", (str(revision),))
        return revision

    @staticmethod
    def _item(row):
        return {key: row[key] for key in ("id", "name", "quantity", "store", "added_on", "version")}

    def _check_link(self, row):
        if row is None:
            raise GroceryError("unauthorized", "Open the private checklist link to continue.", 401)
        if row["revoked_at"] is not None:
            raise GroceryError("link_closed", "This checklist link has been closed. Ask for a new link in WhatsApp.", 410)
        if self.clock() >= row["expires_at"]:
            raise GroceryError("link_expired", "This checklist link has expired. Ask for a new link in WhatsApp.", 410)
        return {"link_id": row["id"], "expires_at": row["expires_at"], "server_time": self.clock()}

    def _require_session(self, conn, session_token, link_id=None):
        if not isinstance(session_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", session_token):
            raise GroceryError("unauthorized", "Open the private checklist link to continue.", 401)
        row = conn.execute("SELECT links.* FROM sessions JOIN links ON links.id = sessions.link_id WHERE sessions.token_hash = ?", (_hash(session_token),)).fetchone()
        if row is not None and link_id is not None and row["id"] != link_id:
            raise GroceryError("unauthorized", "This browser session belongs to a different checklist link.", 401)
        return self._check_link(row)

    def snapshot(self, session_token=None, link_id=None):
        with self._transaction() as conn:
            if session_token is not None or link_id is not None:
                self._require_session(conn, session_token, link_id)
            items = [self._item(row) for row in conn.execute("SELECT * FROM items WHERE removed_at IS NULL ORDER BY CASE WHEN store = 'Unassigned' THEN 1 ELSE 0 END, store COLLATE NOCASE, added_on, id")]
            return {"items": items, "revision": self._revision(conn), "server_time": self.clock()}

    @staticmethod
    def _operation(conn, operation_id, payload):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if operation_id is not None:
            operation_id = _text(operation_id, "operation_id", 128)
            prior = conn.execute("SELECT payload, result FROM operations WHERE id = ?", (operation_id,)).fetchone()
            if prior:
                if prior["payload"] != encoded:
                    raise GroceryError("operation_conflict", "This operation ID was already used for a different request.", 409)
                return encoded, json.loads(prior["result"])
        return encoded, None

    @staticmethod
    def _receipt(conn, operation_id, payload, result):
        if operation_id is not None:
            conn.execute("INSERT INTO operations VALUES (?, ?, ?)", (operation_id.strip(), payload, json.dumps(result)))
        return result

    def _history_entry(self, conn, action, item, details=""):
        conn.execute("INSERT INTO history (timestamp,action,item_id,name,quantity,store,details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (_iso(self.clock()), action, item["id"], item["name"], item["quantity"], item["store"], details or f'{item["name"]} ({item["quantity"]})'))

    def add_item(self, name, quantity="1", store="Unassigned", expected_revision=None, operation_id=None):
        name, quantity, store = _text(name, "name"), _text(quantity, "quantity", 100), _text(store, "store", 200)
        if expected_revision is not None:
            _integer(expected_revision, "expected_revision")
        with self._transaction(write=True) as conn:
            payload, prior = self._operation(conn, operation_id, ["add", name, quantity, store, expected_revision])
            if prior is not None:
                return prior
            if expected_revision is not None and self._revision(conn) != expected_revision:
                raise GroceryError("revision_conflict", "The list changed. Reload it and repeat the duplicate check before adding.", 409)
            item = {"id": str(uuid.uuid4()), "name": name, "quantity": quantity, "store": store,
                    "added_on": _iso(self.clock()), "version": 1}
            conn.execute("INSERT INTO items (id,name,quantity,store,added_on,version) VALUES (:id,:name,:quantity,:store,:added_on,:version)", item)
            self._history_entry(conn, "ADD", item)
            result = {"item": item, "revision": self._bump(conn)}
            return self._receipt(conn, operation_id, payload, result)

    def update_item(self, item_id, version, *, name=None, quantity=None, store=None, action="UPDATE", operation_id=None):
        item_id, version = _text(item_id, "id", 100), _integer(version, "version")
        if action not in ("UPDATE", "MERGE"):
            raise GroceryError("invalid_input", "Update action must be UPDATE or MERGE.")
        changes = {key: _text(value, key, limit) for key, value, limit in
                   (("name", name, 500), ("quantity", quantity, 100), ("store", store, 200)) if value is not None}
        if not changes:
            raise GroceryError("invalid_input", "Provide a name, quantity, or store to update.")
        with self._transaction(write=True) as conn:
            payload, prior = self._operation(conn, operation_id, ["update", item_id, version, action, changes])
            if prior is not None:
                return prior
            row = conn.execute("SELECT * FROM items WHERE id = ? AND removed_at IS NULL", (item_id,)).fetchone()
            if row is None:
                raise GroceryError("not_found", "This item is no longer on the grocery list.", 404)
            if row["version"] != version:
                raise GroceryError("item_conflict", "This item changed. Reload it before applying your change.", 409)
            item = self._item(row)
            before = dict(item)
            item.update(changes)
            item["version"] += 1
            conn.execute("UPDATE items SET name=:name, quantity=:quantity, store=:store, version=:version WHERE id=:id", item)
            self._history_entry(conn, action, item, json.dumps({"before": before, "after": item}, ensure_ascii=False, sort_keys=True))
            result = {"item": item, "revision": self._bump(conn)}
            return self._receipt(conn, operation_id, payload, result)

    def remove_item(self, item_id, version, *, session_token=None, link_id=None, operation_id=None):
        item_id, version = _text(item_id, "id", 100), _integer(version, "version")
        with self._transaction(write=True) as conn:
            if session_token is not None or link_id is not None:
                self._require_session(conn, session_token, link_id)
            payload, prior = self._operation(conn, operation_id, ["remove", item_id, version])
            if prior is not None:
                return prior
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise GroceryError("not_found", "This item does not exist.", 404)
            if row["removed_at"] is not None:
                result = {"removed": False, "id": item_id, "revision": self._revision(conn)}
            else:
                if row["version"] != version:
                    raise GroceryError("item_conflict", "This item changed. Reload it before checking it off.", 409)
                conn.execute("UPDATE items SET removed_at = ?, version = version + 1 WHERE id = ?", (_iso(self.clock()), item_id))
                self._history_entry(conn, "REMOVE", self._item(row))
                result = {"removed": True, "id": item_id, "revision": self._bump(conn)}
            return self._receipt(conn, operation_id, payload, result)

    def history(self):
        with self._transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM history ORDER BY id")]

    @staticmethod
    def _link_token(conn, link_id):
        key = bytes.fromhex(conn.execute("SELECT value FROM metadata WHERE key = 'signing_key'").fetchone()[0])
        digest = hmac.new(key, ("grocery-link-v1:" + link_id).encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue_link(self):
        with self._transaction(write=True) as conn:
            now = self.clock()
            row = conn.execute("SELECT * FROM links WHERE revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC LIMIT 1", (now,)).fetchone()
            if row:
                return {"link_id": row["id"], "token": self._link_token(conn, row["id"]),
                        "created_at": row["created_at"], "expires_at": row["expires_at"], "reused": True}
            link_id = str(uuid.uuid4())
            token = self._link_token(conn, link_id)
            conn.execute("INSERT INTO links VALUES (?, ?, ?, ?, NULL)", (link_id, _hash(token), now, now + LINK_TTL))
            return {"link_id": link_id, "token": token, "created_at": now, "expires_at": now + LINK_TTL, "reused": False}

    def exchange_token(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise GroceryError("unauthorized", "This private checklist link is invalid.", 401)
        with self._transaction(write=True) as conn:
            row = conn.execute("SELECT * FROM links WHERE token_hash = ?", (_hash(token),)).fetchone()
            info = self._check_link(row)
            session_token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions VALUES (?, ?)", (_hash(session_token), info["link_id"]))
            return {"session_token": session_token, **info}

    def session(self, session_token, link_id=None):
        with self._transaction() as conn:
            return self._require_session(conn, session_token, link_id)

    def close_link(self, session_token, link_id):
        with self._transaction(write=True) as conn:
            info = self._require_session(conn, session_token, link_id)
            conn.execute("UPDATE links SET revoked_at = ? WHERE id = ?", (self.clock(), info["link_id"]))
            return {"closed": True, "link_id": info["link_id"]}

    def revoke_link(self):
        """Local-administrator recovery command; never exposed on an unauthenticated API."""
        with self._transaction(write=True) as conn:
            result = conn.execute("UPDATE links SET revoked_at = ? WHERE revoked_at IS NULL", (self.clock(),))
            return {"closed": True, "links_revoked": result.rowcount}

    def export_markdown(self, output_dir):
        output_dir = Path(output_dir).expanduser().resolve()
        if output_dir == self.data_dir:
            raise GroceryError("invalid_input", "Export into a different directory so original legacy files are preserved.")
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._transaction() as conn:
            items = [self._item(row) for row in conn.execute("SELECT * FROM items WHERE removed_at IS NULL ORDER BY CASE WHEN store = 'Unassigned' THEN 1 ELSE 0 END, store COLLATE NOCASE, added_on, id")]
            entries = [dict(row) for row in conn.execute("SELECT * FROM history ORDER BY id")]
            revision = self._revision(conn)
        lines, last_store = ["# Grocery List", ""], None
        for item in items:
            if item["store"] != last_store:
                lines.extend(["", "## " + item["store"], ""])
                last_store = item["store"]
            lines.append(f'- {item["name"]} ({item["quantity"]}) — added on {item["added_on"]}')
        hist = ["# Grocery History", ""]
        for entry in entries:
            detail = entry["details"] if entry["item_id"] is None else f'{entry["name"]} ({entry["quantity"]})'
            hist.append(f'- {entry["timestamp"]} | {entry["action"]} | {detail} | {entry["store"]}')
        # Refuse any pre-existing destination, including symlinks; exports never overwrite.
        destinations = [output_dir / "list.md", output_dir / "history.md"]
        if any(os.path.lexists(path) for path in destinations):
            raise GroceryError("invalid_input", "Export destination already contains list.md or history.md; choose a new directory.")
        for path, content in zip(destinations, (lines, hist)):
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(content).strip() + "\n")
        return {"files": [str(path) for path in destinations], "revision": revision}

    def backup(self, output_file):
        target = Path(output_file).expanduser().resolve()
        if target == self.db_path:
            raise GroceryError("invalid_input", "Backup destination must differ from the live database.")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise GroceryError("invalid_input", "Backup destination already exists; choose a new file.") from exc
        os.close(fd)
        source, destination = self._connect(), sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return {"database": str(target)}
