import concurrent.futures
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from grocery_service.cli import main
from grocery_service.store import GroceryError, LINK_TTL, Store


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data"
        self.clock = Clock()
        self.store = Store(self.path, self.clock)
        self.store.initialize()

    def add(self, name="Milk", **kwargs):
        return self.store.add_item(name, **kwargs)["item"]

    def session(self):
        link = self.store.issue_link()
        return self.store.exchange_token(link["token"])

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(GroceryError) as raised:
            function(*args, **kwargs)
        self.assertEqual(code, raised.exception.code)
        return raised.exception

    def test_add_remove_and_atomic_history(self):
        item = self.add(quantity="2L", store="Costco", expected_revision=0)
        self.assertEqual(1, self.store.snapshot()["revision"])
        self.assertTrue(item["added_on"].endswith("Z"))
        result = self.store.remove_item(item["id"], item["version"])
        self.assertTrue(result["removed"])
        self.assertEqual(2, result["revision"])
        self.assertEqual([], self.store.snapshot()["items"])
        history = self.store.history()
        self.assertEqual(["ADD", "REMOVE"], [entry["action"] for entry in history])
        self.assertTrue(all(entry["item_id"] == item["id"] for entry in history))

    def test_item_update_blocks_stale_checkbox(self):
        item = self.add()
        changed = self.store.update_item(item["id"], 1, quantity="3L", action="MERGE")
        self.assertEqual(2, changed["item"]["version"])
        self.assert_error("item_conflict", self.store.remove_item, item["id"], 1)
        self.assert_error("item_conflict", self.store.update_item, item["id"], 1, quantity="4L")
        self.assertEqual("3L", self.store.snapshot()["items"][0]["quantity"])
        self.assertEqual(["ADD", "MERGE"], [entry["action"] for entry in self.store.history()])
        self.store.remove_item(item["id"], 2)

    def test_remove_old_id_cannot_remove_readded_item(self):
        item = self.add()
        self.store.remove_item(item["id"], 1)
        replacement = self.add()
        self.assertNotEqual(item["id"], replacement["id"])
        self.assertFalse(self.store.remove_item(item["id"], 1)["removed"])
        self.assertEqual([replacement], self.store.snapshot()["items"])
        self.assertEqual(3, len(self.store.history()))

    def test_mutation_retry_receipts_and_conflicting_operation(self):
        result = self.store.add_item("Milk", expected_revision=0, operation_id="add-1")
        self.assertEqual(result, self.store.add_item("Milk", expected_revision=0, operation_id="add-1"))
        self.assert_error("operation_conflict", self.store.add_item, "Eggs", expected_revision=0, operation_id="add-1")
        item = result["item"]
        updated = self.store.update_item(item["id"], 1, quantity="2L", operation_id="update-1")
        self.assertEqual(updated, self.store.update_item(item["id"], 1, quantity="2L", operation_id="update-1"))
        self.assert_error("operation_conflict", self.store.update_item, item["id"], 1, quantity="3L", operation_id="update-1")
        removed = self.store.remove_item(item["id"], 2, operation_id="remove-1")
        self.assertEqual(removed, self.store.remove_item(item["id"], 2, operation_id="remove-1"))
        self.assert_error("operation_conflict", self.store.remove_item, item["id"], 1, operation_id="remove-1")
        self.assertEqual(3, len(self.store.history()))

    def test_concurrent_different_items_preserved(self):
        first, second = self.add("Milk"), self.add("Eggs")
        barrier = threading.Barrier(2)

        def remove(item):
            store = Store(self.path, self.clock)
            barrier.wait()
            return store.remove_item(item["id"], 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(remove, [first, second]))
        self.assertTrue(all(result["removed"] for result in results))
        self.assertEqual(4, self.store.snapshot()["revision"])
        self.assertEqual([], self.store.snapshot()["items"])
        self.assertEqual(4, len(self.store.history()))

    def test_concurrent_same_item_removed_and_logged_once(self):
        item = self.add()
        barrier = threading.Barrier(2)

        def remove(_):
            store = Store(self.path, self.clock)
            barrier.wait()
            return store.remove_item(item["id"], 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(remove, [1, 2]))
        self.assertEqual([False, True], sorted(result["removed"] for result in results))
        self.assertEqual(2, len(self.store.history()))

    def test_concurrent_adds_require_fresh_duplicate_decision(self):
        barrier = threading.Barrier(2)

        def add(_):
            store = Store(self.path, self.clock)
            barrier.wait()
            try:
                return store.add_item("Milk", expected_revision=0)
            except GroceryError as exc:
                return exc.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(add, [1, 2]))
        self.assertEqual(1, results.count("revision_conflict"))
        self.assertEqual(1, len(self.store.snapshot()["items"]))

    def test_concurrent_issue_reuses_single_shared_link(self):
        barrier = threading.Barrier(3)

        def issue(_):
            store = Store(self.path, self.clock)
            barrier.wait()
            return store.issue_link()

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            links = list(pool.map(issue, [1, 2, 3]))
        self.assertEqual(1, len({link["token"] for link in links}))
        self.assertEqual(1, len({link["link_id"] for link in links}))
        self.assertEqual(1, sum(not link["reused"] for link in links))

    def test_link_reuse_restart_exact_ttl_boundary(self):
        initial = self.store.issue_link()
        session = self.store.exchange_token(initial["token"])
        self.clock.now += 7200
        restarted = Store(self.path, self.clock)
        restarted.initialize()
        reused = restarted.issue_link()
        self.assertEqual(initial["token"], reused["token"])
        self.assertEqual(initial["expires_at"], reused["expires_at"])
        self.assertEqual(initial["created_at"] + LINK_TTL, reused["expires_at"])
        self.assertTrue(reused["reused"])
        self.assertEqual(initial["link_id"], restarted.session(session["session_token"])["link_id"])
        self.clock.now = initial["expires_at"] - 0.001
        restarted.session(session["session_token"])
        self.clock.now = initial["expires_at"]
        self.assert_error("link_expired", restarted.session, session["session_token"])
        self.assert_error("link_expired", restarted.exchange_token, initial["token"])
        replacement = restarted.issue_link()
        self.assertNotEqual(initial["token"], replacement["token"])
        self.assertEqual(self.clock.now + LINK_TTL, replacement["expires_at"])

    def test_close_revokes_all_sessions_and_preserves_data(self):
        item = self.add()
        link = self.store.issue_link()
        first, second = [self.store.exchange_token(link["token"]) for _ in range(2)]
        self.store.close_link(first["session_token"], link["link_id"])
        for session in (first, second):
            self.assert_error("link_closed", self.store.snapshot, session_token=session["session_token"], link_id=link["link_id"])
            self.assert_error("link_closed", self.store.remove_item, item["id"], 1, session_token=session["session_token"], link_id=link["link_id"])
        self.assert_error("link_closed", self.store.exchange_token, link["token"])
        self.assertEqual([item], self.store.snapshot()["items"])
        self.assertEqual(1, len(self.store.history()))
        self.assertNotEqual(link["token"], self.store.issue_link()["token"])

    def test_session_link_binding_and_invalid_credentials(self):
        session = self.session()
        self.assert_error("unauthorized", self.store.session, session["session_token"], "different-link")
        self.assert_error("unauthorized", self.store.session, "random")
        self.assert_error("unauthorized", self.store.exchange_token, "random")
        self.assert_error("unauthorized", self.store.exchange_token, "\ud800" * 43)
        self.assert_error("unauthorized", self.store.session, "\ud800" * 43)
        self.assert_error("unauthorized", self.store.snapshot, link_id=session["link_id"])

    def test_expired_auth_rejects_even_successful_operation_retry(self):
        item = self.add()
        session = self.session()
        self.store.remove_item(item["id"], 1, session_token=session["session_token"], operation_id="check-1")
        self.clock.now = session["expires_at"]
        self.assert_error("link_expired", self.store.remove_item, item["id"], 1, session_token=session["session_token"], operation_id="check-1")

    def test_close_and_remove_are_serializable(self):
        item = self.add()
        session = self.session()
        barrier = threading.Barrier(2)

        def close():
            store = Store(self.path, self.clock)
            barrier.wait()
            return store.close_link(session["session_token"], session["link_id"])

        def remove():
            store = Store(self.path, self.clock)
            barrier.wait()
            try:
                return store.remove_item(item["id"], 1, session_token=session["session_token"], link_id=session["link_id"])
            except GroceryError as exc:
                return exc.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            closed, removed = pool.submit(close), pool.submit(remove)
            self.assertTrue(closed.result()["closed"])
            result = removed.result()
        # Whichever transaction wins the lock is authoritative. No partial removal/history.
        if result == "link_closed":
            self.assertEqual([item], self.store.snapshot()["items"])
            self.assertEqual(1, len(self.store.history()))
        else:
            self.assertTrue(result["removed"])
            self.assertEqual([], self.store.snapshot()["items"])
            self.assertEqual(2, len(self.store.history()))
        self.assert_error("link_closed", self.store.session, session["session_token"])

    def test_tokens_not_stored_in_plaintext(self):
        link = self.store.issue_link()
        session = self.store.exchange_token(link["token"])
        with contextlib.closing(sqlite3.connect(self.store.db_path)) as conn:
            dump = "\n".join(conn.iterdump())
        self.assertNotIn(link["token"], dump)
        self.assertNotIn(session["session_token"], dump)
        self.assertEqual(0, self.store.db_path.stat().st_mode & 0o007)

    def test_initialize_as_trusted_group_member_does_not_chmod_owner_file(self):
        other_user = self.store.db_path.stat().st_uid + 1
        with mock.patch("grocery_service.store.os.geteuid", return_value=other_user), mock.patch("grocery_service.store.os.chmod") as chmod:
            self.assertTrue(self.store.initialize()["already_initialized"])
            chmod.assert_not_called()
        self.store.db_path.chmod(0o664)
        with mock.patch("grocery_service.store.os.geteuid", return_value=other_user), mock.patch("grocery_service.store.os.chmod") as chmod:
            self.assert_error("permissions_error", self.store.initialize)
            chmod.assert_not_called()

    def test_backup_consistent_and_export_does_not_overwrite(self):
        self.add("Milk", store="Costco")
        backup = Path(self.temp.name) / "backup.sqlite3"
        self.store.backup(backup)
        with contextlib.closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
        self.assertEqual(0, backup.stat().st_mode & 0o077)
        self.assert_error("invalid_input", self.store.backup, backup)
        destination = Path(self.temp.name) / "export"
        self.store.export_markdown(destination)
        self.assertIn("## Costco", (destination / "list.md").read_text())
        self.assertIn("| ADD | Milk", (destination / "history.md").read_text())
        self.assert_error("invalid_input", self.store.export_markdown, self.path)
        self.assert_error("invalid_input", self.store.export_markdown, destination)

    def test_failed_mutation_does_not_change_revision_or_history(self):
        self.assert_error("revision_conflict", self.store.add_item, "Milk", expected_revision=99)
        self.assert_error("invalid_input", self.store.add_item, "Milk\nBread")
        self.assert_error("invalid_input", self.store.add_item, "Milk\ud800")
        self.assert_error("invalid_input", self.store.add_item, "Milk", expected_revision=True)
        self.assertEqual(0, self.store.snapshot()["revision"])
        self.assertEqual([], self.store.history())

    def test_history_failure_rolls_back_item(self):
        with contextlib.closing(sqlite3.connect(self.store.db_path)) as conn:
            conn.execute("CREATE TRIGGER reject_history BEFORE INSERT ON history BEGIN SELECT RAISE(ABORT, 'fail'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_item("Milk")
        self.assertEqual([], self.store.snapshot()["items"])
        self.assertEqual(0, self.store.snapshot()["revision"])

    def test_cli_list_add_link_and_errors(self):
        def command(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = main(["--data-dir", str(self.path), *args])
            return status, json.loads(out.getvalue() or err.getvalue())

        status, initial = command("list")
        self.assertEqual(0, status)
        status, added = command("add", "--name", "Milk", "--expected-revision", str(initial["revision"]), "--operation-id", "cli-1")
        self.assertEqual(0, status)
        self.assertEqual("Milk", added["item"]["name"])
        status, link = command("link")
        self.assertEqual(0, status)
        self.assertTrue(link["url"].startswith("https://hadol.deydas.com/grocery/#key="))
        self.assertNotIn("token", link)
        status, local = command("link", "--base-url", "http://127.0.0.1:8765/grocery/")
        self.assertEqual(0, status)
        self.assertTrue(local["url"].startswith("http://127.0.0.1:8765/grocery/#key="))
        status, error = command("link", "--base-url", "http://groceries.example/grocery/")
        self.assertEqual(1, status)
        self.assertEqual("invalid_input", error["error"]["code"])
        status, error = command("add", "--name", "Eggs", "--expected-revision", "0")
        self.assertEqual(1, status)
        self.assertEqual("revision_conflict", error["error"]["code"])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = Store(self.path)

    def test_import_mixed_v1_v2_and_legacy_removal_formats_once(self):
        listing = """# Grocery List
<!-- multiline
comment -->
## Costco
- Milk (2L) — added by Nita on 2026-03-10
- Eggs (x12) — added on 2026-03-11
## Unassigned
- Bread (1) — added on 2026-03-12T10:00:00-07:00
"""
        history = """# Grocery History
- 2026-03-10 09:14 | ADD | Milk (2L) | Costco | by Nita
- 2026-03-11 14:02 | ADD | Eggs (x12) | Costco
- 2026-03-12 08:30 | MERGE | eggs x12+x6→x18 | Costco | by Nita + Abhishek
[2026-03-13 10:05] REMOVE: milk (2L) from Costco — by Nita
2026-03-13 11:05 REMOVE: milk (2L) from Costco
"""
        (self.path / "list.md").write_text(listing)
        (self.path / "history.md").write_text(history)
        (self.path / "config.json").write_text('{"custom":true}')
        (self.path / "safety.json").write_text('{"risks":[{"item":"peanuts"}]}')
        first = self.store.initialize()
        self.assertEqual(3, first["migration"]["items"])
        self.assertEqual(5, first["migration"]["history"])
        self.assertEqual(listing, (self.path / "list.md").read_text())
        self.assertEqual(history, (self.path / "history.md").read_text())
        self.assertEqual('{"custom":true}', (self.path / "config.json").read_text())
        self.assertIn("peanuts", (self.path / "safety.json").read_text())
        entries = self.store.history()
        self.assertEqual("eggs x12+x6→x18", entries[2]["details"])
        self.assertTrue(all("by Nita" not in entry["details"] for entry in entries))
        bread = next(item for item in self.store.snapshot()["items"] if item["name"] == "Bread")
        self.assertEqual("2026-03-12T17:00:00Z", bread["added_on"])
        milk = next(item for item in self.store.snapshot()["items"] if item["name"] == "Milk")
        self.assertEqual("2026-03-10", milk["added_on"])
        ids = [item["id"] for item in self.store.snapshot()["items"]]
        again = self.store.initialize()
        self.assertTrue(again["already_initialized"])
        self.assertEqual(ids, [item["id"] for item in self.store.snapshot()["items"]])
        self.assertEqual(5, len(self.store.history()))

    def test_empty_import_marker_prevents_later_reimport(self):
        self.store.initialize()
        (self.path / "list.md").write_text("# Grocery List\n## Costco\n- Milk (2L) — added on 2026-03-10\n")
        self.store.initialize()
        self.assertEqual([], self.store.snapshot()["items"])

    def test_malformed_import_fails_atomically_and_can_be_fixed(self):
        path = self.path / "list.md"
        path.write_text("# Grocery List\n## Costco\n- Milk (2L) — added on 2026-03-10\n- unknown row\n")
        with self.assertRaises(GroceryError) as raised:
            self.store.initialize()
        self.assertEqual("migration_error", raised.exception.code)
        self.assertIn("list.md:4", raised.exception.message)
        path.write_text("# Grocery List\n## Costco\n- Milk (2L) — added on 2026-03-10\n")
        self.store.initialize()
        self.assertEqual(1, len(self.store.snapshot()["items"]))

    def test_malformed_history_rolls_back_entire_import(self):
        (self.path / "list.md").write_text("# Grocery List\n## Costco\n- Milk (2L) — added on 2026-03-10\n")
        (self.path / "history.md").write_text("# Grocery History\nSomething happened\n")
        with self.assertRaises(GroceryError) as raised:
            self.store.initialize()
        self.assertEqual("migration_error", raised.exception.code)
        (self.path / "history.md").write_text("# Grocery History\n")
        self.assertEqual(1, self.store.initialize()["migration"]["items"])

    def test_no_import_is_persistent_even_with_legacy_files(self):
        (self.path / "list.md").write_text("unrecognized data that user explicitly chose not to import")
        self.assertTrue(self.store.initialize(import_legacy=False)["migration"]["skipped"])
        self.assertTrue(self.store.initialize()["already_initialized"])
        self.assertEqual([], self.store.snapshot()["items"])


if __name__ == "__main__":
    unittest.main()
