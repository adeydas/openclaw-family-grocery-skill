"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

const script = readFileSync(join(__dirname, "../grocery_service/static/app.js"), "utf8");

// Exercise the real application with a small DOM/fetch harness. Browser visual,
// native focus, cookie, and cross-client behavior still need browser/API checks.
class Element {
  constructor(tag = "div") {
    Object.assign(this, {
      tagName: tag, children: [], parentNode: null, dataset: {}, attrs: {},
      handlers: {}, hidden: false, disabled: false, value: "", textContent: "",
      classList: { toggle() {} },
    });
  }
  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }
  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }
  replaceChildren(...nodes) {
    for (const child of [...this.children]) child.remove();
    this.append(...nodes);
  }
  insertBefore(node, before) {
    node.remove();
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, node);
    node.parentNode = this;
  }
  get lastElementChild() { return this.children.at(-1); }
  get childElementCount() { return this.children.length; }
  get options() { return this.children; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  querySelector() { return this.children[0]; }
  closest(tag) {
    let node = this;
    while (node && node.tagName !== tag) node = node.parentNode;
    return node;
  }
  focus() { this.document.activeElement = this; }
}

async function fixture({ pinned = null, token = "test-token", items = [], safety = [], notices = [] } = {}) {
  const time = { local: 1800000000000, server: 1800007200000 };
  const elements = new Map();
  const calls = [];
  const intervals = new Map();
  const storage = new Map(pinned ? [["grocery_link_id", pinned]] : []);
  const world = { closed: false, revision: 1, items, safety, notices, removeFailure: null, closeFailure: false };
  const document = {
    activeElement: null, hidden: false, handlers: {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, this.createElement("div"));
      return elements.get(id);
    },
    createElement(tag) {
      const node = new Element(tag);
      node.document = this;
      return node;
    },
    createTextNode(text) {
      const node = this.createElement("text");
      node.textContent = text;
      return node;
    },
    addEventListener(name, fn) { this.handlers[name] = fn; },
  };
  document.getElementById("close-link").append(document.createElement("span"));
  document.getElementById("store-filter").append(document.createElement("option"));
  const window = {
    handlers: {}, reloads: 0,
    location: {
      hash: token ? "#key=" + token : "", pathname: "/grocery/", search: "",
      reload() { window.reloads++; },
    },
    history: { replaceState() { window.location.hash = ""; } },
    sessionStorage: {
      getItem(key) { return storage.get(key) || null; },
      setItem(key, value) { storage.set(key, value); },
    },
    setTimeout() { return 1; }, clearTimeout() {},
    addEventListener(name, fn) { this.handlers[name] = fn; },
    setInterval(fn, delay) { intervals.set(delay, fn); },
  };
  class ClockDate extends Date { static now() { return time.local; } }
  const expiresAt = time.server / 1000 + 14400;
  const session = () => ({ link_id: "link-a", server_time: time.server / 1000, expires_at: expiresAt });
  const response = (status, data) => ({ ok: status === 200, status, json: async () => JSON.parse(JSON.stringify(data)) });
  async function fetch(url, options) {
    calls.push({ url, options });
    if (world.closed && !url.endsWith("close")) {
      return response(410, { error: { code: "link_closed", message: "Closed" } });
    }
    if (url.includes("session")) return response(200, session());
    if (url.endsWith("close")) {
      if (world.closeFailure) throw new TypeError("Network connection lost");
      world.closed = true;
      return response(200, { closed: true });
    }
    if (url.includes("/remove")) {
      const failure = world.removeFailure;
      world.removeFailure = null;
      if (failure === "network") throw new TypeError("Network connection lost");
      if (failure === "stale") {
        world.items[0].version++;
        world.items[0].quantity = "3 L";
        world.revision++;
        return response(409, { error: { code: "item_conflict", message: "The item changed" } });
      }
      const id = url.split("/")[2];
      world.items = world.items.filter(item => item.id !== id);
      world.revision++;
      return response(200, { removed: true, revision: world.revision });
    }
    return response(200, {
      ...session(), revision: world.revision, items: world.items, stores: [],
      safety: world.safety, notices: world.notices,
    });
  }
  const context = vm.createContext({
    document, window, fetch, Date: ClockDate, URLSearchParams, URL, AbortController,
    crypto: webcrypto,
    Option: function (text, value) {
      const node = document.createElement("option");
      node.textContent = text;
      node.value = value;
      return node;
    },
  });
  vm.runInContext(script, context);
  const flush = async () => {
    for (let i = 0; i < 10; i++) await new Promise(setImmediate);
  };
  await flush();
  const get = id => elements.get(id);
  const rows = () => get("store-groups").children.flatMap(group => group.children[2].children);
  const check = async index => {
    const input = rows()[index].children[0].children[0];
    input.checked = true;
    input.handlers.change();
    await flush();
  };
  const poll = async () => { intervals.get(3000)(); await flush(); };
  return { get, calls, time, intervals, window, storage, world, flush, rows, check, poll };
}

const milk = () => ({
  id: "milk", name: "2% milk", quantity: "2 L", store: "Market",
  added_on: "2026-10-12", version: 1,
});
const removals = app => app.calls.filter(call => call.url.includes("/remove"));

test("epoch timestamps honor four-hour TTL despite client clock skew", async () => {
  const app = await fixture();
  assert.equal(app.window.location.hash, "", "private fragment is removed immediately");
  assert.equal(app.storage.get("grocery_link_id"), "link-a");
  assert.equal(app.get("checklist").hidden, false);
  assert.equal(app.get("expiry-countdown").textContent, "4h 0m");
  assert.match(app.calls[1].url, /link_id=link-a/);
  app.time.local += 14401000;
  app.intervals.get(1000)();
  assert.equal(app.get("checklist").hidden, true);
  assert.match(app.get("entry-title").textContent, /expired/);
  const before = app.calls.length;
  await app.poll();
  assert.equal(app.calls.length, before, "expired tabs stop polling");
});

test("Close revokes the pinned link and hides the list after server acknowledgement", async () => {
  const app = await fixture();
  await app.get("close-link").handlers.click();
  assert.equal(app.world.closed, true);
  assert.match(app.get("entry-title").textContent, /closed/);
  assert.equal(JSON.parse(app.calls.at(-1).options.body).link_id, "link-a");
  assert.equal(app.get("checklist").hidden, true);
});

test("a failed Close never claims the link was revoked", async () => {
  const app = await fixture();
  app.world.closeFailure = true;
  await app.get("close-link").handlers.click();
  assert.equal(app.world.closed, false);
  assert.equal(app.get("checklist").hidden, false);
  assert.match(app.get("action-message").textContent, /may still be active/);
  assert.equal(app.get("close-link").disabled, true);
});

test("a fresh fragment link reloads a closed tab; unrelated or empty fragments do not", async () => {
  const app = await fixture();
  await app.get("close-link").handlers.click();
  assert.match(app.get("entry-title").textContent, /closed/);
  for (const fragment of ["#store=Market", "#key=", ""]) {
    app.window.location.hash = fragment;
    app.window.handlers.hashchange();
    assert.equal(app.window.reloads, 0);
  }
  app.window.location.hash = "#key=fresh-private-token";
  app.window.handlers.hashchange();
  assert.equal(app.window.reloads, 1, "a new page bootstrap must consume the fresh private token");
});

test("an old tab cannot inherit a different link from a newer cookie", async () => {
  const app = await fixture({ pinned: "older-link", token: null });
  assert.match(app.calls[0].url, /link_id=older-link/);
  assert.equal(app.calls.length, 1, "mismatched session must never load the new list");
  assert.equal(app.get("checklist").hidden, true);
});

test("safety matches simple plurals and whole phrases; notices remain exact", async () => {
  const app = await fixture({
    items: [milk(), { ...milk(), id: "eggs", name: "Free-range eggs" }, { ...milk(), id: "unrelated", name: "chickenpox" }],
    safety: [{ item: "milk", risk: "Milk warning" }, { item: "egg", risk: "Egg warning" }, { item: "chicken", risk: "Must not appear" }],
    notices: [{ item: "milk", risk: "Wrong exact-name notice" }],
  });
  const rows = app.rows();
  assert.equal(rows[0].children[1].children[0].textContent, "Milk warning");
  assert.equal(rows[0].children[1].children.length, 1);
  assert.equal(rows[1].children[1].children[0].textContent, "Egg warning");
  assert.equal(rows[2].children[1].hidden, true);
  await app.poll();
  assert.equal(app.rows()[0], rows[0], "unchanged polling preserves existing row nodes");
});

test("a stale quantity refreshes the row and requires another deliberate check", async () => {
  const app = await fixture({ items: [milk()] });
  app.world.removeFailure = "stale";
  await app.check(0);
  assert.equal(removals(app).length, 1, "the changed item must not be automatically removed");
  assert.equal(app.get("remaining-count").textContent, "1");
  assert.equal(app.rows()[0].children[0].children[2].textContent, "3 L");
  assert.match(app.get("action-message").textContent, /review it before checking it off again/);
  await app.check(0);
  const payload = JSON.parse(removals(app).at(-1).options.body);
  assert.equal(payload.version, 2);
  assert.equal(payload.link_id, "link-a");
  assert.equal(app.get("remaining-count").textContent, "0");
});

test("an uncertain removal keeps the same operation ID when retried after reconnect", async () => {
  const app = await fixture({ items: [milk()] });
  app.world.removeFailure = "network";
  await app.check(0);
  assert.equal(app.get("remaining-count").textContent, "1");
  assert.equal(app.rows()[0].children[0].children[0].disabled, true);
  await app.poll();
  await app.check(0);
  const [first, second] = removals(app).map(call => JSON.parse(call.options.body));
  assert.match(first.operation_id, /^[a-z0-9-]{36}$/);
  assert.equal(second.operation_id, first.operation_id);
  assert.equal(app.get("remaining-count").textContent, "0");
});
