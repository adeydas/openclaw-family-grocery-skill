"""Exercise the real WSGI and storage boundary without a running web server."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from grocery_service.store import Store, LINK_TTL
from grocery_service.web import Application, create_app, MAX_BODY


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1791828000.0
        self.store = Store(self.temp.name, clock=lambda: self.now)
        self.store.initialize()
        self.item = self.store.add_item("Milk", "2L", "Whole Foods")["item"]
        self.link = self.store.issue_link()
        self.app = Application(self.store, "https://hadol.deydas.com/grocery/")

    def request(self, path="api/list", method="GET", body=None, cookie=None,
                origin="https://hadol.deydas.com", query=None, content_type="application/json",
                raw=None, content_length=None):
        encoded = raw if raw is not None else json.dumps(body).encode() if body is not None else b""
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/grocery/" + path,
               "QUERY_STRING": urlencode(query or {}), "wsgi.input": io.BytesIO(encoded),
               "CONTENT_LENGTH": str(len(encoded) if content_length is None else content_length),
               "CONTENT_TYPE": content_type}
        if cookie is not None:
            env["HTTP_COOKIE"] = cookie
        if origin is not None:
            env["HTTP_ORIGIN"] = origin
        captured = {}
        def start_response(status, headers):
            captured.update(status=int(status.split()[0]), headers=dict(headers))
        payload = b"".join(self.app(env, start_response))
        if captured["headers"]["Content-Type"].startswith("application/json") and method != "HEAD":
            payload = json.loads(payload)
        return captured["status"], payload, captured["headers"]

    def login(self, link=None):
        status, data, headers = self.request("api/session", "POST", {"token": (link or self.link)["token"]})
        self.assertEqual(status, 200, data)
        self.assertNotIn("session_token", data)
        self.assertNotIn("token", data)
        return headers["Set-Cookie"].split(";", 1)[0], data, headers

    def remove(self, cookie, *, version=None, operation="remove-1", item=None, link=None):
        item = item or self.item
        return self.request(f'api/items/{item["id"]}/remove', "POST", {
            "link_id": (link or self.link)["link_id"],
            "version": item["version"] if version is None else version,
            "operation_id": operation,
        }, cookie=cookie)

    def test_public_shell_is_generic_and_uncached(self):
        for path in ("", "index.html", "app.js", "app.css", "healthz"):
            status, data, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertNotIn(self.link["token"], str(data))
            self.assertNotIn(self.item["id"], str(data))
        self.assertEqual(self.request("healthz")[1], {"status": "ok"})
        self.assertEqual(self.request("", method="HEAD")[1], b"")

    def test_every_private_api_requires_auth(self):
        for path in ("api/session", "api/list"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.remove(None)[0], 401)
        self.assertEqual(self.request("api/close", "POST", {"link_id": self.link["link_id"]})[0], 401)
        self.assertEqual(self.request("api/session", "POST", {"token": "not-a-token"})[0], 401)
        self.assertEqual(self.request("api/list", cookie="grocery_session=unknown")[0], 401)

    def test_cookie_scoped_secure_and_session_can_resume(self):
        cookie, data, headers = self.login()
        for attribute in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/grocery/", "Max-Age=14400"):
            self.assertIn(attribute, headers["Set-Cookie"])
        self.assertEqual(data["expires_at"], self.now + LINK_TTL)
        self.assertEqual(data["server_time"], self.now)
        self.assertEqual(self.request("api/session", cookie=cookie)[1], data)
        self.assertEqual(self.request(cookie=cookie)[0], 400)  # List requests must pin identity.
        result = self.request(cookie=cookie, query={"link_id": self.link["link_id"]})
        self.assertEqual(result[0], 200)
        self.assertEqual(result[1]["items"], [self.item])
        self.assertEqual(result[1]["expires_at"], self.now + LINK_TTL)

    def test_all_posts_require_exact_origin_and_json(self):
        cookie, _, _ = self.login()
        routes = [("api/session", {"token": self.link["token"]}),
                  ("api/close", {"link_id": self.link["link_id"]}),
                  (f'api/items/{self.item["id"]}/remove', {"link_id": self.link["link_id"], "version": 1, "operation_id": "x"})]
        for path, body in routes:
            for origin in (None, "null", "https://evil.example", "https://hadol.deydas.com.evil.example"):
                self.assertEqual(self.request(path, "POST", body, cookie=cookie, origin=origin)[0], 403)
            self.assertEqual(self.request(path, "POST", body, cookie=cookie, content_type="text/plain")[0], 415)
        self.assertEqual(len(self.store.snapshot()["items"]), 1)
        self.assertEqual(self.store.issue_link()["link_id"], self.link["link_id"])

    def test_validation_and_unknown_routes_do_not_mutate(self):
        cookie, _, _ = self.login()
        for raw, size, status in [(b"{", None, 400), (b"[]", None, 400), (b"", None, 413), (b"{}", MAX_BODY + 1, 413)]:
            self.assertEqual(self.request("api/session", "POST", raw=raw, content_length=size)[0], status)
        for version in (True, -1, 0, "1", 1.5):
            self.assertEqual(self.remove(cookie, version=version)[0], 400)
        for path in ("../grocery.sqlite3", "config.json", "api/link", "api/items", "api/admin", "api/close"):
            self.assertEqual(self.request(path, cookie=cookie)[0], 404)
        self.assertEqual(self.request("api/session", "POST", {"token": 123})[0], 400)
        self.assertEqual(len(self.store.snapshot()["items"]), 1)

    def test_close_revokes_every_browser_without_deleting_items(self):
        first, _, _ = self.login()
        second, _, _ = self.login()
        status, result, _ = self.request("api/close", "POST", {"link_id": self.link["link_id"]}, cookie=first)
        self.assertEqual(status, 200)
        self.assertTrue(result["closed"])
        for cookie in (first, second):
            self.assertEqual(self.request(cookie=cookie, query={"link_id": self.link["link_id"]})[0], 410)
            self.assertEqual(self.remove(cookie)[0], 410)
        self.assertEqual(self.request("api/session", "POST", {"token": self.link["token"]})[0], 410)
        self.assertEqual(len(self.store.snapshot()["items"]), 1)
        self.assertNotEqual(self.store.issue_link()["link_id"], self.link["link_id"])

    def test_expiry_is_absolute_including_open_session_and_retry(self):
        cookie, _, _ = self.login()
        self.assertEqual(self.remove(cookie)[0], 200)
        self.now += LINK_TTL - 1
        _, _, headers = self.login()
        self.assertIn("Max-Age=1", headers["Set-Cookie"])
        self.assertEqual(self.store.issue_link()["link_id"], self.link["link_id"])
        self.now += 1
        self.assertEqual(self.request("api/session", cookie=cookie)[0], 410)
        self.assertEqual(self.request(cookie=cookie, query={"link_id": self.link["link_id"]})[0], 410)
        self.assertEqual(self.remove(cookie)[0], 410)  # Even a previously successful replay.
        self.assertEqual(self.request("api/close", "POST", {"link_id": self.link["link_id"]}, cookie=cookie)[0], 410)
        self.assertEqual(self.request("api/session", "POST", {"token": self.link["token"]})[0], 410)

    def test_stale_tab_cannot_use_new_cookie_for_old_link(self):
        old_cookie, _, _ = self.login()
        self.store.revoke_link()
        new_link = self.store.issue_link()
        new_cookie, _, _ = self.login(new_link)
        self.assertEqual(self.remove(new_cookie)[0], 401)
        self.assertEqual(self.request("api/session", cookie=new_cookie, query={"link_id": self.link["link_id"]})[0], 401)
        status, _, headers = self.request("api/close", "POST", {"link_id": self.link["link_id"]}, cookie=new_cookie)
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(self.request(cookie=new_cookie, query={"link_id": new_link["link_id"]})[0], 200)
        self.assertEqual(self.remove(old_cookie)[0], 410)

    def test_version_conflict_then_remove_and_retry(self):
        cookie, _, _ = self.login()
        changed = self.store.update_item(self.item["id"], self.item["version"], quantity="4L")["item"]
        status, data, _ = self.remove(cookie)
        self.assertEqual((status, data["error"]["code"]), (409, "item_conflict"))
        result = self.remove(cookie, item=changed)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.remove(cookie, item=changed)[1], result[1])
        self.assertEqual(self.remove(cookie, item=changed, operation="second-person")[1]["removed"], False)
        self.assertEqual(len([h for h in self.store.history() if h["action"] == "REMOVE"]), 1)
        self.assertEqual(self.remove(cookie, version=1)[0], 409)  # Changed payload for used operation.

    def test_session_persists_across_app_restart(self):
        cookie, _, _ = self.login()
        self.app = Application(Store(self.temp.name, clock=lambda: self.now), "https://hadol.deydas.com/grocery/")
        self.assertEqual(self.request(cookie=cookie, query={"link_id": self.link["link_id"]})[0], 200)

    def test_metadata_is_fresh_and_malformed_data_degrades(self):
        cookie, _, _ = self.login()
        root = Path(self.temp.name)
        (root / "config.json").write_text(json.dumps({"stores": [{"name": "Whole Foods", "address": "123 Test", "hours": "9–5"}]}))
        (root / "safety.json").write_text(json.dumps({"risks": [{"item": "milk", "risk": "Example note", "alternatives": ["Other"]}]}))
        (root / "health-notices.json").write_text(json.dumps({"checked_at": "2026-10-12T00:00:00Z", "notices": []}))
        data = self.request(cookie=cookie, query={"link_id": self.link["link_id"]})[1]
        self.assertEqual(data["stores"][0]["address"], "123 Test")
        self.assertEqual(data["safety"][0]["risk"], "Example note")
        self.assertEqual(data["notices_checked_at"], "2026-10-12T00:00:00Z")
        (root / "safety.json").write_text("{")
        status, data, _ = self.request(cookie=cookie, query={"link_id": self.link["link_id"]})
        self.assertEqual(status, 200)
        self.assertIn("metadata_warning", data)
        self.assertEqual(data["items"], [self.item])

    def test_insecure_cookies_restricted_to_loopback_and_init_required(self):
        for url in ("http://hadol.deydas.com/grocery/", "https://hadol.deydas.com/grocery/"):
            with self.assertRaises(ValueError):
                Application(self.store, url, cookie_secure=False)
        with self.assertRaises(ValueError):
            Application(self.store, "http://127.0.0.1:8787/grocery/")
        self.app = Application(self.store, "http://127.0.0.1:8787/grocery/", cookie_secure=False)
        status, _, headers = self.request("api/session", "POST", {"token": self.link["token"]}, origin="http://127.0.0.1:8787")
        self.assertEqual(status, 200)
        self.assertNotIn("Secure", headers["Set-Cookie"])
        with self.assertRaises(RuntimeError):
            create_app(data_dir=str(Path(self.temp.name) / "missing"))

    def test_factory_rejects_incomplete_migration_without_initializing(self):
        data = Path(self.temp.name) / "failed-import"
        data.mkdir()
        (data / "grocery.sqlite3").touch()
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            create_app(data_dir=str(data))
        self.assertFalse((data / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
