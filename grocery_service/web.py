"""Small same-origin WSGI application, served by Gunicorn behind Nginx.

There are deliberately no public administration or link-creation endpoints.
The agent operates through the local CLI and the same SQLite transaction code.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import GroceryError, Store

MAX_BODY = 16 * 1024
COOKIE = "grocery_session"
STATIC = Path(__file__).with_name("static")


def read_metadata(data_dir: Path) -> dict:
    """Read optional metadata fresh; bad metadata must not hide the live list."""
    result = {"stores": [], "safety": [], "notices": [], "notices_checked_at": None}
    warnings = []
    for filename, key, field in (
        ("config.json", "stores", "stores"),
        ("safety.json", "risks", "safety"),
        ("health-notices.json", "notices", "notices"),
    ):
        path = data_dir / filename
        if not path.exists():
            continue
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("metadata too large")
            value = json.loads(path.read_text(encoding="utf-8"))
            entries = value[key]
            if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
                raise ValueError("invalid metadata")
            if field == "stores":
                result[field] = [
                    {k: str(row.get(k, "")) for k in ("name", "address", "hours")}
                    for row in entries
                ]
            elif field == "safety":
                result[field] = [
                    {"item": str(row.get("item", "")), "risk": str(row.get("risk", "")),
                     "alternatives": [str(x) for x in row.get("alternatives", [])]
                     if isinstance(row.get("alternatives", []), list) else []}
                    for row in entries
                ]
            else:
                # An agent-refreshed cache, not an assertion of a live inventory/health check.
                result[field] = [
                    {k: str(row.get(k, "")) for k in ("item", "risk", "url")}
                    for row in entries
                ]
                result["notices_checked_at"] = value.get("checked_at")
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append({
                "stores": "Store details are unavailable right now.",
                "safety": "Saved safety notes are unavailable right now.",
                "notices": "Saved health notices are unavailable right now.",
            }[field])
    if warnings:
        result["metadata_warning"] = " ".join(warnings)
    return result


class Application:
    def __init__(self, store: Store, public_url: str, cookie_secure: bool = True):
        parsed = urlsplit(public_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("GROCERY_PUBLIC_URL must be an absolute origin and path, without credentials, query or fragment")
        if cookie_secure and parsed.scheme != "https":
            raise ValueError("Production GROCERY_PUBLIC_URL must use HTTPS")
        if not cookie_secure and (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("Insecure cookies are permitted only for HTTP loopback development")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.prefix = parsed.path.rstrip("/") + "/"
        if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*", self.prefix):
            raise ValueError("Public URL path must consist of simple directory names")
        self.store = store
        self.data_dir = Path(store.data_dir)
        self.cookie_secure = cookie_secure

    def __call__(self, environ, start_response):
        status, data, mime, extra = 200, b"", "application/json; charset=utf-8", []
        try:
            status, payload, mime, extra = self.dispatch(environ)
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except GroceryError as exc:
            status = exc.status
            data = json.dumps({"error": {"code": exc.code, "message": str(exc)}}).encode("utf-8")
        except sqlite3.OperationalError:
            status = 503
            data = b'{"error":{"code":"storage_busy","message":"The list is busy. Please retry."}}'
        except Exception:
            # Never echo raw tokens, cookie values, request bodies, or data paths.
            status = 500
            data = b'{"error":{"code":"internal_error","message":"Could not save or load the list. Please retry."}}'
        headers = [
            ("Content-Type", mime), ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
            ("X-Robots-Tag", "noindex, nofollow, noarchive"),
            ("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"),
        ] + extra
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [data if environ.get("REQUEST_METHOD") != "HEAD" else b""]

    def token(self, environ):
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get("HTTP_COOKIE", ""))
            value = cookie.get(COOKIE)
            token = value.value if value else ""
        except Exception:
            token = ""
        if not token or len(token) > 256:
            raise GroceryError("unauthorized", "Open the private link from WhatsApp to access your checklist.", 401)
        return token

    def body(self, environ):
        if environ.get("HTTP_ORIGIN") != self.origin:
            raise GroceryError("origin_denied", "This request did not come from the checklist.", 403)
        if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
            raise GroceryError("invalid_input", "A JSON request is required.", 415)
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            raise GroceryError("invalid_input", "Invalid request size.", 400)
        if size < 1 or size > MAX_BODY:
            raise GroceryError("invalid_input", "Request is empty or too large.", 413)
        try:
            value = json.loads(environ["wsgi.input"].read(size))
        except (ValueError, UnicodeError):
            raise GroceryError("invalid_input", "Invalid JSON request.", 400)
        if not isinstance(value, dict):
            raise GroceryError("invalid_input", "A JSON object is required.", 400)
        return value

    @staticmethod
    def required_text(value, field, limit=256):
        text = value.get(field)
        if not isinstance(text, str) or not text or len(text) > limit:
            raise GroceryError("invalid_input", f"Invalid {field}.", 400)
        return text

    def cookie_header(self, token, expires_at, server_time):
        cookie = SimpleCookie()
        cookie[COOKIE] = token
        cookie[COOKIE]["path"] = self.prefix
        cookie[COOKIE]["httponly"] = True
        cookie[COOKIE]["samesite"] = "Strict"
        cookie[COOKIE]["max-age"] = max(0, int(expires_at - server_time))
        if self.cookie_secure:
            cookie[COOKIE]["secure"] = True
        return ("Set-Cookie", cookie.output(header="").strip())

    def dispatch(self, env):
        method, path = env.get("REQUEST_METHOD", "GET"), env.get("PATH_INFO", "")
        mime, extra = "application/json; charset=utf-8", []
        if self.prefix != "/" and path == self.prefix[:-1] and method in ("GET", "HEAD"):
            return 308, b"", "text/plain", [("Location", self.prefix)]
        if not path.startswith(self.prefix):
            raise GroceryError("not_found", "Not found.", 404)
        route = path[len(self.prefix):]
        if route == "healthz" and method in ("GET", "HEAD"):
            # Reads DB as a readiness check, without exposing any state.
            self.store.snapshot()
            return 200, {"status": "ok"}, mime, extra
        if route in ("", "index.html", "app.js", "app.css") and method in ("GET", "HEAD"):
            filename = route or "index.html"
            mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8"}[filename]
            return 200, (STATIC / filename).read_bytes(), mime, extra
        if route == "api/session" and method == "POST":
            body = self.body(env)
            session = self.store.exchange_token(self.required_text(body, "token"))
            extra.append(self.cookie_header(session.pop("session_token"), session["expires_at"], session["server_time"]))
            return 200, session, mime, extra
        if route in ("api/session", "api/list") and method == "GET":
            token = self.token(env)
            params = parse_qs(env.get("QUERY_STRING", ""))
            link_id = params.get("link_id", [None])[0]
            session = self.store.session(token, link_id=link_id)
            if route == "api/session":
                return 200, session, mime, extra
            if not link_id:
                raise GroceryError("invalid_input", "The checklist link ID is required.", 400)
            snapshot = self.store.snapshot(session_token=token, link_id=link_id)
            snapshot.update(read_metadata(self.data_dir))
            snapshot.update({"link_id": session["link_id"], "expires_at": session["expires_at"]})
            return 200, snapshot, mime, extra
        match = re.fullmatch(r"api/items/([A-Za-z0-9_-]{1,128})/remove", route)
        if match and method == "POST":
            body = self.body(env)
            token, link_id = self.token(env), self.required_text(body, "link_id")
            version = body.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise GroceryError("invalid_input", "Invalid item version.", 400)
            result = self.store.remove_item(
                match[1], version, session_token=token, link_id=link_id,
                operation_id=self.required_text(body, "operation_id", 128),
            )
            return 200, result, mime, extra
        if route == "api/close" and method == "POST":
            body = self.body(env)
            result = self.store.close_link(self.token(env), self.required_text(body, "link_id"))
            # Do not clear a newer cookie here: an old tab must not log out a new link.
            return 200, result or {"closed": True}, mime, extra
        raise GroceryError("not_found", "Not found.", 404)


def create_app(data_dir=None, public_url=None, cookie_secure=None):
    data_dir = data_dir or os.environ.get("GROCERY_DATA_DIR")
    if not data_dir or not (Path(data_dir) / "grocery.sqlite3").is_file():
        raise RuntimeError("Initialize GROCERY_DATA_DIR with family-grocery init before starting the service")
    if cookie_secure is None:
        cookie_secure = os.environ.get("GROCERY_COOKIE_SECURE", "1") != "0"
    store = Store(data_dir)
    # A failed legacy import can leave an empty SQLite file behind. Do not let
    # a file's existence alone pass startup or implicitly perform a migration.
    try:
        store.snapshot()
    except (sqlite3.Error, TypeError) as exc:
        raise RuntimeError("Grocery storage is not ready; check permissions and complete family-grocery init") from exc
    return Application(
        store,
        public_url or os.environ.get("GROCERY_PUBLIC_URL", "https://hadol.deydas.com/grocery/"),
        cookie_secure,
    )
