// The picker: a centered dialog over the browser window, driven from the
// keyboard. It renders only what visibleRows and hints return, so rows of
// another space exist in the DOM only once Tab revealed them. All text goes
// through textContent.

import { armsAt, delayOf, isArmed, mayDispatch } from "../lib/arming.mjs";
import { TIMING } from "../lib/config.mjs";
import { headerText } from "../lib/header.mjs";
import { hints, initialState, reduce, visibleRows } from "../lib/state.mjs";
import { startLive, startSnapshots } from "./preview.sys.mjs";

const HTML = "http://www.w3.org/1999/xhtml";
// Zen's wrapper around the browser UI (tests/acceptance/test_platform.py S2).
const MOUNT = "zen-main-app-wrapper";
const NO_PREVIEW = "No preview";
const PREVIEW_W = 800;
const PREVIEW_H = 500;
// Keys the picker owns. Every other key reaches the search input.
const OWNED = new Set([
  "Escape",
  "Tab",
  "Enter",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
]);

export function openPicker(
  win,
  model,
  {
    onEffect,
    onReveal = null,
    browserFor,
    previewMode,
    cssUrl,
    PageThumbs,
    site = null,
    now = () => ChromeUtils.now(),
    delayMs = TIMING.defaultDelayMs,
  }
) {
  const doc = win.document;
  const mount = doc.getElementById(MOUNT);
  if (!mount) {
    throw new Error("no-mount");
  }
  // One picker per window (P22).
  if (doc.getElementById("zen-share-picker")) {
    throw new Error("already-open");
  }
  const el = (tag, props = {}) => {
    const node = doc.createElementNS(HTML, tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "text") {
        node.textContent = v;
      } else if (k === "class") {
        node.className = v;
      } else {
        node.setAttribute(k, v);
      }
    }
    return node;
  };

  let state = initialState(model);
  let open = true;
  let previewStopped = false;
  const before = doc.activeElement;
  // P33: Enter and Share commit only once armed, when the delay has passed
  // since the picker opened or its window was last activated.
  const times = {
    openedAt: now(),
    activatedAt: null,
    delayMs: delayOf(delayMs, TIMING.defaultDelayMs),
  };
  let armTimer = null;

  const root = el("div", {
    id: "zen-share-picker",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "zen-share-picker-header",
  });
  const sheet = el("link", { rel: "stylesheet", href: cssUrl });
  // P37: Zen's prompt is hidden, so the header names the asking site.
  const header = el("div", {
    id: "zen-share-picker-header",
    role: "heading",
    "aria-level": "2",
    text: headerText(site),
  });
  const left = el("div", { class: "zsp-left" });
  const search = el("input", {
    id: "zen-share-picker-search",
    type: "search",
    placeholder: "Search tabs",
    "aria-controls": "zen-share-picker-list",
    autocomplete: "off",
  });
  const list = el("div", {
    id: "zen-share-picker-list",
    role: "listbox",
    "aria-label": "Tabs",
  });
  const hintBox = el("div", { class: "zsp-hints" });
  left.append(search, list, hintBox);

  const preview = el("div", { id: "zen-share-picker-preview" });
  const canvas = el("canvas", { class: "zsp-canvas" });
  canvas.width = PREVIEW_W;
  canvas.height = PREVIEW_H;
  const none = el("div", { class: "zsp-no-preview", text: NO_PREVIEW });
  preview.append(canvas, none);

  const buttons = el("div", { class: "zsp-buttons" });
  const cancelBtn = el("button", {
    id: "zen-share-picker-cancel",
    type: "button",
    text: "Cancel",
  });
  const shareBtn = el("button", {
    id: "zen-share-picker-share",
    type: "button",
    text: "Share",
  });
  shareBtn.disabled = true;
  buttons.append(cancelBtn, shareBtn);
  // A press on a button keeps focus in the search box (P22).
  for (const b of [cancelBtn, shareBtn]) {
    b.addEventListener("mousedown", e => e.preventDefault());
  }
  root.append(sheet, header, left, preview, buttons);

  // The tab the preview shows, as {deviceId, browser}, or null.
  let shown = null;
  const showNone = () => {
    canvas.hidden = true;
    none.hidden = false;
  };
  let loop = null;
  if (previewMode === "snapshot") {
    loop = startSnapshots(win, {
      canvas,
      PageThumbs,
      intervalMs: TIMING.snapshotMs,
      onPaint(browser) {
        if (shown && shown.browser === browser) {
          canvas.dataset.deviceId = shown.deviceId;
          canvas.hidden = false;
          none.hidden = true;
        }
      },
      onClear() {
        delete canvas.dataset.deviceId;
      },
    });
  } else if (previewMode === "live") {
    canvas.hidden = true;
    loop = startLive(win, preview);
  }

  function stopPreview() {
    if (previewStopped) {
      return;
    }
    previewStopped = true;
    shown = null;
    try {
      loop?.stop();
    } finally {
      delete canvas.dataset.deviceId;
      showNone();
    }
  }

  // The highlighted tab row, only if it is visible.
  function highlighted(rows) {
    if (state.highlight === null || state.highlight === model.os.key) {
      return null;
    }
    return rows.find(r => r.key === state.highlight) ?? null;
  }

  function updatePreview(rows) {
    if (previewStopped) {
      return;
    }
    const row = highlighted(rows);
    if (previewMode === "live") {
      none.hidden = row !== null;
      loop.setTarget(row ? row.deviceId : null);
      return;
    }
    if (previewMode !== "snapshot") {
      showNone();
      return;
    }
    let browser = null;
    if (row) {
      try {
        browser = browserFor(row.deviceId) ?? null;
      } catch {
        browser = null;
      }
    }
    if (shown && shown.browser === browser && browser !== null) {
      return;
    }
    shown = browser ? { deviceId: row.deviceId, browser } : null;
    showNone();
    loop.setTarget(browser);
  }

  // Group labels for the other spaces, by row key.
  const groupOf = new Map();
  model.others.forEach((g, i) => {
    for (const r of g.rows) {
      groupOf.set(r.key, i);
    }
  });

  function rowNode(row, index) {
    const node = el("div", {
      id: "zen-share-picker-row-" + index,
      class: "zsp-row",
      role: "option",
      "data-group": row.key === model.os.key ? "os" : row.group,
    });
    node.dataset.key = row.key;
    const selected = row.key === state.highlight;
    node.setAttribute("aria-selected", selected ? "true" : "false");
    if (row.key === model.os.key) {
      node.append(el("span", { class: "zsp-title", text: row.label }));
    } else {
      const icon = el("img", { class: "zsp-icon", alt: "" });
      if (row.icon) {
        icon.setAttribute("src", row.icon);
      } else {
        icon.hidden = true;
      }
      const text = el("span", { class: "zsp-text" });
      text.append(
        el("span", { class: "zsp-title", text: row.title }),
        el("span", { class: "zsp-host", text: row.host })
      );
      node.append(icon, text);
      if (row.group === "other") {
        node.append(el("span", { class: "zsp-careful", text: "careful" }));
      }
    }
    node.addEventListener("mousedown", e => e.preventDefault());
    node.addEventListener("click", () => dispatch({ type: "click", key: row.key }));
    return node;
  }

  function render() {
    const rows = visibleRows(model, state);
    const nodes = [];
    let lastGroup = null;
    let selectedNode = null;
    rows.forEach((row, i) => {
      const g = groupOf.get(row.key);
      if (row.group === "other" && g !== undefined && g !== lastGroup) {
        nodes.push(
          el("div", {
            class: "zsp-space-header",
            role: "presentation",
            text: model.others[g].label,
          })
        );
      }
      lastGroup = row.group === "other" ? g : null;
      const node = rowNode(row, i);
      if (row.key === state.highlight) {
        selectedNode = node;
      }
      nodes.push(node);
    });
    list.replaceChildren(...nodes);
    hintBox.replaceChildren(
      ...hints(model, state).map(h => {
        const node = el("div", { class: "zsp-hint", text: h.text });
        node.dataset.hint = h.code;
        return node;
      })
    );
    if (selectedNode) {
      search.setAttribute("aria-activedescendant", selectedNode.id);
      selectedNode.scrollIntoView({ block: "nearest" });
    } else {
      search.removeAttribute("aria-activedescendant");
    }
    updatePreview(rows);
  }

  function report(effect) {
    try {
      onEffect(effect);
    } catch (e) {
      console.error(`[zen-share-picker] onEffect failed: ${e?.name ?? "error"}`);
    }
  }

  function dispatch(action) {
    if (!open) {
      return;
    }
    const out = reduce(model, state, action);
    const revealed = !state.revealed && out.state.revealed;
    state = out.state;
    const effect = out.effect;
    if (effect && effect.type === "cancel") {
      close();
      report(effect);
      return;
    }
    render();
    if (revealed && onReveal) {
      try {
        onReveal();
      } catch (e) {
        console.error(`[zen-share-picker] onReveal failed: ${e?.name ?? "error"}`);
      }
    }
    if (effect) {
      report(effect);
    }
  }

  // P33: a commit before arming, from an auto-repeat or from an untrusted
  // event is ignored: no state change and no effect. P36: so is a cancel
  // from an auto-repeat or an untrusted event; arming never gates it.
  function gated(action, e) {
    if (mayDispatch(action, { trusted: e.isTrusted, repeat: e.repeat }, times, now())) {
      dispatch(action);
    }
  }

  // Share is disabled until armed; a timer enables it.
  function syncArmed() {
    if (armTimer !== null) {
      win.clearTimeout(armTimer);
      armTimer = null;
    }
    if (!open) {
      return;
    }
    const t = now();
    const armed = isArmed(times, t);
    shareBtn.disabled = !armed;
    const wait = armsAt(times) - t;
    if (!armed && Number.isFinite(wait)) {
      armTimer = win.setTimeout(syncArmed, Math.max(1, Math.ceil(wait)));
    }
  }

  function onActivate() {
    times.activatedAt = now();
    syncArmed();
  }

  function onKeyDown(e) {
    if (!OWNED.has(e.key) || e.isComposing) {
      return;
    }
    if (e.altKey || e.ctrlKey || e.metaKey) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey && e.key === "Tab") {
      // P10: swallowed, no action.
      return;
    }
    gated({ type: "key", key: e.key }, e);
  }

  // P44: an Escape that the hidden panel's guard took for this window,
  // wherever focus was. The same rules as an Escape in the picker.
  function escape(e) {
    if (e.isComposing || e.altKey || e.ctrlKey || e.metaKey) {
      return;
    }
    gated({ type: "key", key: "Escape" }, e);
  }

  function close() {
    if (!open) {
      return;
    }
    open = false;
    if (armTimer !== null) {
      win.clearTimeout(armTimer);
      armTimer = null;
    }
    win.removeEventListener("activate", onActivate, true);
    stopPreview();
    root.remove();
    if (before && before.isConnected && doc.activeElement !== before) {
      try {
        before.focus();
      } catch {
        // The element can no longer take focus; leave focus where it is.
      }
    }
  }

  root.addEventListener("keydown", onKeyDown, true);
  search.addEventListener("input", () =>
    dispatch({ type: "query", text: search.value })
  );
  shareBtn.addEventListener("click", e => gated({ type: "share" }, e));
  cancelBtn.addEventListener("click", e => gated({ type: "cancel" }, e));

  // As PopupNotifications does: the delay restarts on activate.
  win.addEventListener("activate", onActivate, true);

  // A throw here must not leave a picker without a session: one would stay
  // in the DOM and refuse every later picker in this window.
  try {
    mount.append(root);
    syncArmed();
    render();
    search.focus();
  } catch (e) {
    close();
    throw e;
  }

  return {
    close,
    isOpen: () => open && root.isConnected,
    stopPreview,
    escape,
    search,
  };
}
