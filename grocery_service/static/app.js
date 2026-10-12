"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const ui = {
    entry: $("entry-state"), title: $("entry-title"), description: $("entry-description"),
    symbol: $("entry-symbol"), retry: $("retry-load"), checklist: $("checklist"),
    closeControl: $("close-control"), close: $("close-link"), count: $("remaining-count"),
    countLabel: $("remaining-label"), connection: $("connection-state"),
    connectionLabel: $("connection-label"), connectionMessage: $("connection-message"),
    countdown: $("expiry-countdown"), expiryAt: $("expiry-at"), filter: $("store-filter"),
    groups: $("store-groups"), empty: $("empty-state"), emptyTitle: $("empty-title"),
    emptyDescription: $("empty-description"), message: $("action-message"),
    metadata: $("metadata-warning"), footnote: $("safety-footnote"), announcer: $("announcer"),
  };
  const state = {
    linkId: null, expiresAt: 0, clockOffset: 0, terminal: false, authenticated: false,
    connected: false, loaded: false, busy: false, closing: false, revision: -1,
    items: [], stores: [], pending: null, signature: "", filter: "",
  };
  const groupNodes = new Map();
  const itemNodes = new Map();
  const operations = new Map();
  const controllers = new Set();
  let groupSequence = 0;
  let snapshotPromise = null;
  let refreshRequested = false;
  let bootstrapPromise = null;
  let messageTimer = null;
  let token = new URLSearchParams(window.location.hash.slice(1)).get("key");

  // A fragment is never sent in an HTTP request. Remove it before doing other work.
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  function readPinnedLink() {
    try { return window.sessionStorage.getItem("grocery_link_id"); } catch (_) { return null; }
  }

  function pinLink(linkId) {
    try { window.sessionStorage.setItem("grocery_link_id", linkId); } catch (_) { /* Keep it in memory. */ }
  }

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    controllers.add(controller);
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`api/${path}`, {
        method: options.method || "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: options.body ? { "Content-Type": "application/json", "Accept": "application/json" } : { "Accept": "application/json" },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
      let data;
      try { data = await response.json(); } catch (_) {
        throw new ApiError(response.status, "invalid_response", "We couldn't read the response. Please try again.");
      }
      if (!response.ok) {
        throw new ApiError(response.status, data.error?.code || "request_failed", data.error?.message || "That change couldn't be saved.");
      }
      return data;
    } finally {
      window.clearTimeout(timeout);
      controllers.delete(controller);
    }
  }

  function announce(text) { ui.announcer.textContent = text; }

  function showMessage(text, persistent = false) {
    window.clearTimeout(messageTimer);
    ui.message.textContent = text;
    ui.message.hidden = !text;
    if (text && !persistent) messageTimer = window.setTimeout(() => { ui.message.hidden = true; }, 9000);
  }

  function showEntry(title, description, symbol, retry = false) {
    ui.title.textContent = title;
    ui.description.textContent = description;
    ui.symbol.textContent = symbol;
    ui.retry.hidden = !retry;
    ui.entry.hidden = false;
    ui.checklist.hidden = true;
    ui.closeControl.hidden = true;
  }

  function terminate(reason) {
    if (state.terminal) return;
    state.terminal = true;
    state.connected = false;
    token = null;
    for (const controller of controllers) controller.abort();
    state.items = [];
    itemNodes.clear();
    groupNodes.clear();
    operations.clear();
    ui.groups.replaceChildren();
    ui.metadata.textContent = "";
    ui.message.textContent = "";
    if (reason === "closed") {
      showEntry("This checklist link is closed", "Your saved groceries are still there. Ask for your grocery list in WhatsApp to get a fresh link.", "✓");
      announce("This checklist link is closed for everyone.");
    } else if (reason === "expired") {
      showEntry("This checklist link has expired", "Your saved groceries are still there. Ask for your grocery list in WhatsApp to get a new link.", "↗");
      announce("This checklist link has expired.");
    } else {
      showEntry("Open your private checklist link", "Ask for your grocery list in WhatsApp, then open the link to start shopping.", "↗");
      announce("A current private link is needed to open this checklist.");
    }
    ui.title.tabIndex = -1;
    ui.title.focus({ preventScroll: true });
  }

  function handleAccessError(error) {
    if (error.status !== 401 && error.status !== 410 && error.status !== 403) return false;
    const reason = /closed|revoked/.test(error.code) ? "closed" : (error.status === 410 || /expired/.test(error.code) ? "expired" : "invalid");
    terminate(reason);
    return true;
  }

  function instantMillis(value) {
    // Session/list timestamps are Unix seconds; cached metadata may use ISO 8601.
    return typeof value === "number" ? value * 1000 : Date.parse(value);
  }

  function updateClock(data) {
    const serverTime = instantMillis(data.server_time);
    const expiresAt = instantMillis(data.expires_at);
    if (Number.isFinite(serverTime)) state.clockOffset = serverTime - Date.now();
    if (Number.isFinite(expiresAt)) state.expiresAt = expiresAt;
    if (state.expiresAt) {
      ui.expiryAt.textContent = `Closes at ${new Date(state.expiresAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
      ui.expiryAt.title = new Date(state.expiresAt).toLocaleString();
    }
    tick();
  }

  function tick() {
    if (state.terminal || !state.expiresAt) return;
    const seconds = Math.ceil((state.expiresAt - Date.now() - state.clockOffset) / 1000);
    if (seconds <= 0) { terminate("expired"); return; }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    ui.countdown.textContent = hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
  }

  function setConnected(connected) {
    if (state.terminal) return;
    const changed = state.connected !== connected;
    state.connected = connected;
    ui.connection.classList.toggle("is-connected", connected);
    ui.connectionLabel.textContent = connected ? "Live with everyone" : "Reconnecting";
    ui.connectionMessage.hidden = connected;
    ui.connectionMessage.textContent = "Connection lost. We'll refresh your list when you're back online. Wait to check off more items.";
    if (changed && state.loaded) announce(connected ? "You're connected. Your list is up to date." : "Connection lost. Checking items is paused until you reconnect.");
    updateControls();
  }

  function updateControls() {
    const disabled = !state.connected || state.terminal || state.busy;
    ui.close.disabled = disabled;
    ui.close.querySelector("span").textContent = state.closing ? "Closing…" : "Close";
    for (const [id, node] of itemNodes) {
      const pending = state.pending === id;
      node.input.disabled = disabled;
      node.input.checked = pending;
      node.row.classList.toggle("is-saving", pending);
      node.quantity.textContent = pending ? "Saving…" : node.quantityText;
      node.quantity.hidden = !pending && !node.quantityText;
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function storeName(item) { return item.store || "Unassigned"; }
  function itemKey(name) { return String(name || "").trim().toLocaleLowerCase(); }

  function safetyWords(name) {
    return String(name || "").normalize("NFKC").toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu)?.map((word) => {
      if (word.length > 4 && word.endsWith("ies")) return word.slice(0, -3) + "y";
      if (word.length > 4 && /(?:ches|shes|xes|zes|sses)$/.test(word)) return word.slice(0, -2);
      if (word.length > 3 && word.endsWith("s") && !/(?:ss|us|is)$/.test(word)) return word.slice(0, -1);
      return word;
    }) || [];
  }

  function safetyMatches(itemName, noteName) {
    const phrase = safetyWords(noteName).join(" ");
    return Boolean(phrase) && ` ${safetyWords(itemName).join(" ")} `.includes(` ${phrase} `);
  }

  function addedDate(value) {
    if (!value) return "";
    // A YYYY-MM-DD value is a calendar date, not a UTC timestamp.
    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
    const date = dateOnly ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])) : new Date(value);
    return Number.isNaN(date.getTime()) ? `Added ${String(value)}` : `Added ${date.toLocaleDateString([], { month: "short", day: "numeric" })}`;
  }

  function newGroup(name) {
    const section = element("section", "store-group");
    const header = element("div", "store-heading");
    const title = element("h2", "", name);
    title.id = `store-heading-${++groupSequence}`;
    section.setAttribute("aria-labelledby", title.id);
    const count = element("span", "store-count");
    const details = element("p", "store-details");
    const list = element("ul", "store-items");
    header.append(title, count);
    section.append(header, details, list);
    return { section, title, count, details, list };
  }

  function newItem(id) {
    const row = element("li", "grocery-item");
    row.dataset.itemId = id;
    const label = element("label", "item-label");
    const input = element("input", "item-checkbox");
    input.type = "checkbox";
    input.dataset.itemId = id;
    input.addEventListener("change", () => {
      if (input.checked) removeItem(id);
    });
    const copy = element("span", "item-copy");
    const name = element("span", "item-name");
    const meta = element("span", "item-meta");
    const quantity = element("span", "item-quantity");
    const notes = element("div", "item-notes");
    copy.append(name, meta);
    label.append(input, copy, quantity);
    row.append(label, notes);
    return { row, input, name, meta, quantity, notes, quantityText: "", noteSignature: "" };
  }

  function updateNotes(node, item, safety, notices) {
    const match = itemKey(item.name);
    const relevantSafety = safety.filter((note) => safetyMatches(item.name, note.item));
    const relevantNotices = notices.filter((note) => itemKey(note.item) === match);
    const signature = JSON.stringify([relevantSafety, relevantNotices]);
    if (node.noteSignature === signature) return;
    node.noteSignature = signature;
    node.notes.replaceChildren();
    for (const note of relevantSafety) {
      const alternatives = Array.isArray(note.alternatives) ? note.alternatives.join(", ") : note.alternatives;
      const content = `${note.risk || "Safety note"}${alternatives ? ` · Alternatives: ${alternatives}` : ""}`;
      node.notes.append(element("p", "item-note", content));
    }
    for (const note of relevantNotices) {
      const paragraph = element("p", "item-note", note.risk || "Health notice");
      if (note.url) {
        try {
          const url = new URL(note.url);
          if (url.protocol === "https:" || url.protocol === "http:") {
            const link = element("a", "", "Read notice");
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            paragraph.append(document.createTextNode(" · "), link);
          }
        } catch (_) { /* An invalid source URL is not a usable link. */ }
      }
      node.notes.append(paragraph);
    }
    node.notes.hidden = !node.notes.childElementCount;
  }

  function reconcile(parent, nodes) {
    nodes.forEach((node, index) => {
      if (parent.children[index] !== node) parent.insertBefore(node, parent.children[index] || null);
    });
    while (parent.children.length > nodes.length) parent.lastElementChild.remove();
  }

  function applyFilter() {
    state.filter = ui.filter.value;
    let visibleCount = 0;
    for (const [name, node] of groupNodes) {
      node.section.hidden = Boolean(state.filter && name !== state.filter);
      if (!node.section.hidden) visibleCount += node.list.children.length;
    }
    ui.empty.hidden = visibleCount !== 0;
    ui.emptyTitle.textContent = state.items.length ? "This store is all done." : "Everything's in the basket.";
    ui.emptyDescription.textContent = state.items.length ? "Choose another store to see what's left on your list." : "You're all caught up. New items will appear here when they're added.";
  }

  function renderSnapshot(data) {
    state.items = Array.isArray(data.items) ? data.items : [];
    state.stores = Array.isArray(data.stores) ? data.stores : [];
    const safety = Array.isArray(data.safety) ? data.safety : [];
    const notices = Array.isArray(data.notices) ? data.notices : [];
    const signature = JSON.stringify([state.items, state.stores, safety, notices, data.notices_checked_at, data.metadata_warning]);
    if (signature === state.signature) { updateControls(); return; }
    state.signature = signature;

    const activeElement = document.activeElement;
    const activeId = activeElement?.dataset?.itemId;
    const oldVisibleIds = [...itemNodes].filter(([, node]) => !node.row.closest("section").hidden).map(([id]) => id);
    const activeIndex = oldVisibleIds.indexOf(activeId);
    const buckets = new Map();
    const liveIds = new Set();
    for (const item of state.items) {
      const id = String(item.id);
      const store = storeName(item);
      if (!buckets.has(store)) buckets.set(store, []);
      buckets.get(store).push(item);
      liveIds.add(id);
    }
    for (const [id, node] of itemNodes) {
      if (!liveIds.has(id)) { node.row.remove(); itemNodes.delete(id); }
    }
    for (const [name, node] of groupNodes) {
      if (!buckets.has(name)) { node.section.remove(); groupNodes.delete(name); }
    }

    const orderedGroups = [];
    for (const [name, items] of buckets) {
      if (!groupNodes.has(name)) groupNodes.set(name, newGroup(name));
      const group = groupNodes.get(name);
      group.count.textContent = String(items.length);
      group.count.setAttribute("aria-label", `${items.length} ${items.length === 1 ? "item" : "items"}`);
      const store = state.stores.find((entry) => entry.name === name);
      group.details.textContent = [store?.address, store?.hours].filter(Boolean).join(" · ");
      group.details.hidden = !group.details.textContent;
      const orderedItems = items.map((item) => {
        const id = String(item.id);
        if (!itemNodes.has(id)) itemNodes.set(id, newItem(id));
        const node = itemNodes.get(id);
        node.name.textContent = item.name;
        node.meta.textContent = addedDate(item.added_on);
        node.meta.hidden = !node.meta.textContent;
        node.quantityText = item.quantity === null || item.quantity === undefined ? "" : String(item.quantity);
        node.input.setAttribute("aria-label", `Mark ${item.name}${node.quantityText ? `, ${node.quantityText}` : ""}, at ${name}, as bought`);
        updateNotes(node, item, safety, notices);
        return node.row;
      });
      reconcile(group.list, orderedItems);
      orderedGroups.push(group.section);
    }
    reconcile(ui.groups, orderedGroups);

    const storeNames = [...buckets.keys()];
    // Keep a completed selected store available until the shopper chooses another.
    if (state.filter && !storeNames.includes(state.filter)) storeNames.push(state.filter);
    const optionValues = Array.from(ui.filter.options).slice(1).map((option) => option.value);
    if (JSON.stringify(storeNames) !== JSON.stringify(optionValues)) {
      const options = [new Option("All stores", ""), ...storeNames.map((name) => new Option(name, name))];
      ui.filter.replaceChildren(...options);
      ui.filter.value = state.filter;
    }
    ui.count.textContent = String(state.items.length);
    ui.countLabel.textContent = state.items.length === 1 ? "item to pick up" : "items to pick up";
    ui.metadata.textContent = data.metadata_warning ? String(data.metadata_warning) : "";
    ui.metadata.hidden = !ui.metadata.textContent;
    const checkedDate = data.notices_checked_at ? new Date(instantMillis(data.notices_checked_at)) : null;
    ui.footnote.textContent = checkedDate && !Number.isNaN(checkedDate.getTime()) ? `Health notices last checked ${checkedDate.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}.` : "";
    ui.footnote.hidden = !ui.footnote.textContent;
    applyFilter();
    updateControls();

    // Polling leaves existing nodes in place. If an item disappeared, move keyboard
    // focus to its next neighbor rather than dropping it to the document body.
    if (activeId && !itemNodes.has(activeId)) {
      const visible = [...itemNodes.values()].filter((node) => !node.row.closest("section").hidden);
      const next = visible[Math.min(Math.max(activeIndex, 0), visible.length - 1)];
      if (next && !next.input.disabled) next.input.focus({ preventScroll: true });
      else ui.filter.focus({ preventScroll: true });
    } else if (activeId && document.activeElement !== activeElement && itemNodes.has(activeId)) {
      itemNodes.get(activeId).input.focus({ preventScroll: true });
    }
  }

  function refreshList(ensureFresh = false) {
    if (state.terminal || !state.authenticated) return Promise.resolve();
    if (snapshotPromise) {
      if (ensureFresh) refreshRequested = true;
      return snapshotPromise;
    }
    snapshotPromise = (async () => {
      do {
        refreshRequested = false;
        try {
          const data = await request(`list?link_id=${encodeURIComponent(state.linkId)}`);
          if (state.terminal) return;
          if (String(data.link_id) !== state.linkId) { terminate("invalid"); return; }
          updateClock(data);
          if (state.terminal) return;
          // A slow read must never paint an older snapshot over a newer one.
          const revision = Number(data.revision);
          if (!Number.isFinite(revision) || revision >= state.revision) {
            if (Number.isFinite(revision)) state.revision = revision;
            renderSnapshot(data);
          }
          setConnected(true);
          state.loaded = true;
          ui.entry.hidden = true;
          ui.checklist.hidden = false;
          ui.closeControl.hidden = false;
        } catch (error) {
          if (state.terminal || handleAccessError(error)) return;
          setConnected(false);
          if (!state.loaded) showEntry("Your list is taking a moment", "We couldn't connect. Check your connection and try again.", "↻", true);
          return;
        }
      } while (refreshRequested && !state.terminal);
    })().finally(() => { snapshotPromise = null; });
    return snapshotPromise;
  }

  function operationId() {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  async function removeItem(id) {
    tick();
    if (state.busy || !state.connected || state.terminal) { updateControls(); return; }
    const item = state.items.find((entry) => String(entry.id) === id);
    if (!item) { await refreshList(true); return; }
    const key = `${id}:${item.version}`;
    if (!operations.has(key)) operations.set(key, operationId());
    state.busy = true;
    state.pending = id;
    updateControls();
    try {
      await request(`items/${encodeURIComponent(id)}/remove`, {
        method: "POST",
        body: { version: item.version, link_id: state.linkId, operation_id: operations.get(key) },
      });
      if (state.terminal) return;
      operations.delete(key);
      announce(`${item.name} checked off. Saved for everyone.`);
      await refreshList(true);
    } catch (error) {
      if (state.terminal || handleAccessError(error)) return;
      if (error.status === 409) {
        operations.delete(key);
        showMessage(`${item.name} changed while you were shopping. We've refreshed the list; review it before checking it off again.`);
        await refreshList(true);
      } else if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        showMessage(error.message, true);
        await refreshList(true);
      } else {
        setConnected(false);
        showMessage(`We couldn't confirm whether ${item.name} was saved. We'll refresh before you try again.`, true);
      }
    } finally {
      state.pending = null;
      state.busy = false;
      updateControls();
    }
  }

  async function closeLink() {
    tick();
    if (state.busy || !state.connected || state.terminal) return;
    state.busy = true;
    state.closing = true;
    updateControls();
    try {
      await request("close", { method: "POST", body: { link_id: state.linkId } });
      terminate("closed");
    } catch (error) {
      if (state.terminal || handleAccessError(error)) return;
      setConnected(false);
      showMessage("We couldn't confirm that the link closed. It may still be active. Reconnect and try Close again.", true);
    } finally {
      state.busy = false;
      state.closing = false;
      updateControls();
    }
  }

  function bootstrap() {
    if (state.terminal) return Promise.resolve();
    if (bootstrapPromise) return bootstrapPromise;
    if (state.authenticated) return refreshList(true);
    ui.retry.disabled = true;
    bootstrapPromise = (async () => {
      try {
        const pinned = readPinnedLink();
        const data = token
          ? await request("session", { method: "POST", body: { token } })
          : await request(`session${pinned ? `?link_id=${encodeURIComponent(pinned)}` : ""}`);
        if (state.terminal) return;
        if (!data.link_id || (!token && pinned && String(data.link_id) !== pinned)) { terminate("invalid"); return; }
        token = null;
        state.linkId = String(data.link_id);
        pinLink(state.linkId);
        state.authenticated = true;
        updateClock(data);
        if (!state.terminal) await refreshList();
      } catch (error) {
        if (state.terminal || handleAccessError(error)) return;
        showEntry("Let's reconnect", "We couldn't open your checklist. Check your connection and try again.", "↻", true);
      } finally {
        ui.retry.disabled = false;
      }
    })().finally(() => { bootstrapPromise = null; });
    return bootstrapPromise;
  }

  ui.close.addEventListener("click", closeLink);
  ui.retry.addEventListener("click", bootstrap);
  ui.filter.addEventListener("change", applyFilter);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { tick(); bootstrap(); }
  });
  window.addEventListener("focus", () => { tick(); bootstrap(); });
  window.addEventListener("online", () => bootstrap());
  window.addEventListener("offline", () => setConnected(false));
  window.addEventListener("pageshow", (event) => { if (event.persisted) { tick(); bootstrap(); } });
  window.addEventListener("hashchange", () => {
    // Opening a fresh private link in this tab may only change the fragment.
    // Start a new page lifecycle so even a closed tab consumes the new token.
    if (new URLSearchParams(window.location.hash.slice(1)).get("key")) window.location.reload();
  });
  window.setInterval(tick, 1000);
  window.setInterval(() => { if (!document.hidden && !state.terminal && !state.busy) bootstrap(); }, 3000);
  bootstrap();
})();
