"""Local JSON CLI used by OpenClaw; the public website cannot invoke it."""

import argparse
import json
import os
import sqlite3
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

from .store import GroceryError, Store


def parser():
    result = argparse.ArgumentParser(description="Shared grocery list management. Output is JSON.")
    result.add_argument("--data-dir", default=os.environ.get("GROCERY_DATA_DIR"), help="Private grocery data directory (or GROCERY_DATA_DIR)")
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize and import legacy Markdown once, preserving originals")
    init.add_argument("--no-import", action="store_true", help="Skip legacy import permanently for this new database")
    sub.add_parser("list")
    sub.add_parser("history")
    add = sub.add_parser("add")
    add.add_argument("--name", required=True)
    add.add_argument("--quantity", default="1")
    add.add_argument("--store", default="Unassigned")
    add.add_argument("--expected-revision", required=True, type=int, help="Revision returned by list before duplicate checking")
    add.add_argument("--operation-id", default=None, help="Unique request ID; reuse exactly on network/process retry")
    update = sub.add_parser("update")
    update.add_argument("--id", required=True)
    update.add_argument("--version", required=True, type=int)
    update.add_argument("--name")
    update.add_argument("--quantity")
    update.add_argument("--store")
    update.add_argument("--action", choices=("UPDATE", "MERGE"), default="UPDATE")
    update.add_argument("--operation-id", default=None)
    remove = sub.add_parser("remove")
    remove.add_argument("--id", required=True)
    remove.add_argument("--version", required=True, type=int)
    remove.add_argument("--operation-id", default=None)
    link = sub.add_parser("link", help="Issue/reuse four-hour shared link; output is private")
    link.add_argument("--base-url", default=os.environ.get("GROCERY_PUBLIC_URL", os.environ.get("GROCERY_BASE_URL", "https://hadol.deydas.com/grocery/")))
    sub.add_parser("close-link", help="Immediately revoke all active shared links and sessions")
    export = sub.add_parser("export")
    export.add_argument("--output-dir", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--output", required=True, help="New SQLite file; includes private credentials")
    return result


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if not args.data_dir:
        arguments.error("--data-dir or GROCERY_DATA_DIR is required")
    store = Store(args.data_dir)
    try:
        if args.command == "init":
            result = store.initialize(import_legacy=not args.no_import)
        elif not store.db_path.exists():
            raise GroceryError("not_initialized", "Run init before using this data directory.")
        elif args.command == "list":
            result = store.snapshot()
        elif args.command == "history":
            result = store.history()
        elif args.command in ("add", "update", "remove"):
            operation_id = args.operation_id or str(uuid.uuid4())
            if args.command == "add":
                result = store.add_item(args.name, args.quantity, args.store, args.expected_revision, operation_id)
            elif args.command == "update":
                result = store.update_item(args.id, args.version, name=args.name, quantity=args.quantity, store=args.store, action=args.action, operation_id=operation_id)
            else:
                result = store.remove_item(args.id, args.version, operation_id=operation_id)
            result["operation_id"] = operation_id
        elif args.command == "link":
            url = urlsplit(args.base_url)
            local_http = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
            if (url.scheme != "https" and not local_http) or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise GroceryError("invalid_input", "Base URL must use HTTPS (HTTP is allowed only on loopback), without credentials, query, or fragment.")
            _ = url.port  # Validate the port even when only rendering the URL.
            info = store.issue_link()
            result = {key: value for key, value in info.items() if key != "token"}
            result["url"] = urlunsplit((url.scheme, url.netloc, url.path.rstrip("/") + "/", "", "key=" + info["token"]))
        elif args.command == "close-link":
            result = store.revoke_link()
        elif args.command == "export":
            result = store.export_markdown(args.output_dir)
        elif args.command == "backup":
            result = store.backup(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GroceryError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": {"code": "storage_error", "message": str(exc)}}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
