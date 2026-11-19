// Hides Zen's share panel while a picker is open on its prompt (P35).
//
// The rule keeps the panel open, with the same notification, its enable
// delay and its real Allow button working, and lets clicks pass through:
// test_concealed_panel_keeps_allow_working (S6a) and
// test_concealed_panel_lets_clicks_through (S6b) in
// tests/acceptance/test_platform.py. Collapsing the panel closed it.
//
// The rule lives only in style elements that carry MARKER, so it applies
// only while one is in the window. The marker never changes, so revealPanel
// also clears elements an earlier version left.
//
// P48: headful on macOS, Zen (widget.macos.native-popovers) shows the panel
// as a native NSPopover, whose bubble, tail and shadow AppKit draws in its
// own window, out of reach of any style. Gecko shows a plain popup window
// instead when the panel has `nonnative` as it shows, so the add-on sets it
// in `popupshowing` (makeNonnative) and records that it did (NATIVE_MARK
// "added"), or that Gecko had set it already ("kept": headless Gecko sets it
// on every anchored popup). restoreNative takes off only the add-on's own.
// On a plain window Zen's panel rules give the native menu look with
// `!important` (zen-panel-ui.css), so the rule's doubled id outranks them.

const HTML = "http://www.w3.org/1999/xhtml";

export const MARKER = "data-zen-share-picker-conceal";
export const NATIVE_MARK = "data-zen-share-picker-nonnative";
export const ANCHOR_MARK = "data-zen-share-picker-no-open-on-anchor";

const RULE =
  "#notification-popup#notification-popup { opacity: 0 !important;" +
  " pointer-events: none !important; -moz-window-opacity: 0 !important;" +
  " -moz-window-shadow: none !important; appearance: none !important;" +
  " background: transparent !important; }";

// P67: for an arrow panel, Zen's panel.js marks the anchor `open` as it
// shows, which in compact mode slides the sidebar out
// (`zen-compact-mode-active` on #navigator-toolbox, also through Zen's
// has-polyfill on `[open]`), and gives the URL bar `has-popup-open`. It
// skips all of that for a panel with `no-open-on-anchor`. quietAnchor sets
// it before panel.js acts, recording whether it set it ("added") or found
// it ("kept"); releaseAnchor takes off only its own and, when the panel is
// still open, does what panel.js would have done, so a prompt shown again
// looks like stock Zen's.
export function quietAnchor(panel) {
  if (panel.hasAttribute(ANCHOR_MARK)) {
    return;
  }
  if (panel.hasAttribute("no-open-on-anchor")) {
    panel.setAttribute(ANCHOR_MARK, "kept");
    return;
  }
  panel.setAttribute("no-open-on-anchor", "true");
  panel.setAttribute(ANCHOR_MARK, "added");
}

// Never throws.
export function releaseAnchor(win) {
  try {
    const panel = win.PopupNotifications.panel;
    const added = panel.getAttribute(ANCHOR_MARK) === "added";
    panel.removeAttribute(ANCHOR_MARK);
    if (!added) {
      return;
    }
    panel.removeAttribute("no-open-on-anchor");
    const anchor = panel.anchorNode;
    if (panel.state !== "open" || !anchor) {
      return;
    }
    // As panel.js on_popupshowing; its on_popuphiding undoes it later.
    const root = anchor.closest("toolbarbutton, .anchor-root") || anchor;
    const toolbox = root.closest("#navigator-toolbox");
    if (toolbox && win.gZenCompactModeManager?.preference) {
      toolbox.style.transition = "none";
      toolbox.setAttribute("zen-compact-mode-active", "true");
      win.setTimeout(() => {
        toolbox.style.transition = "";
      }, 0);
    }
    root.setAttribute("open", "true");
    if (root.closest("#urlbar") && win.gURLBar) {
      win.gURLBar.setAttribute("has-popup-open", "true");
    }
  } catch {
    // The window is gone.
  }
}

// Makes the panel show as a plain window, recording whether the add-on set
// `nonnative` or found it. Call it before the panel shows.
export function makeNonnative(panel) {
  if (panel.hasAttribute(NATIVE_MARK)) {
    return;
  }
  if (panel.hasAttribute("nonnative")) {
    panel.setAttribute(NATIVE_MARK, "kept");
    return;
  }
  panel.setAttribute("nonnative", "true");
  panel.setAttribute(NATIVE_MARK, "added");
}

// Takes off `nonnative` only if the add-on set it, and its record. Never
// throws.
export function restoreNative(panel) {
  try {
    if (panel.getAttribute(NATIVE_MARK) === "added") {
      panel.removeAttribute("nonnative");
    }
    panel.removeAttribute(NATIVE_MARK);
  } catch {
    // The window is gone.
  }
}

// P44: while the element is in the window, the add-on owns Esc and keeps
// keyboard focus out of the hidden panel, so nothing acts on a prompt the
// user cannot see:
// - Zen's own Esc handler (PopupNotifications.sys.mjs, a capturing keypress
//   listener on the window) presses the top notification's secondary button
//   when focus is on the page or in the panel. A capturing keydown listener
//   on the window cancels every Escape, which also stops its keypress, and
//   hands it to `escape(event)`. P47: it also cancels every chord of the
//   chrome access-key modifiers with a key that is an access key in the
//   panel, which would press Allow or Block from anywhere in the window.
// - A capturing focusin listener on the panel sends focus that enters it to
//   `focusTarget()`, so F6, Tab, Space and Enter never reach its Allow.
// The listeners go with the element: restore() removes both, revealPanel
// removes those of every element it finds, and a listener whose element
// left the window removes itself.
const RELEASE = Symbol.for("zen-share-picker-conceal-release");

function inside(node, root) {
  for (let el = node; el; el = el.parentNode ?? el.host) {
    if (el === root) {
      return true;
    }
  }
  return false;
}

// `ui.key.chromeAccess`, a bitmask: 1 Shift, 2 Ctrl, 4 Alt, 8 Meta. Its
// default is Ctrl on macOS and Alt elsewhere.
function chromeAccessMask() {
  const fallback = Services.appinfo.OS === "Darwin" ? 2 : 4;
  try {
    return Services.prefs.getIntPref("ui.key.chromeAccess", fallback);
  } catch {
    return fallback;
  }
}

// Every access key in the panel, lowercased, read now: the buttons' and
// menu items' `accesskey`, and the ones a notification keeps for its
// buttons.
function accessKeysOf(panel) {
  const keys = [];
  for (const el of panel.querySelectorAll(
    "[accesskey], [buttonaccesskey], [secondarybuttonaccesskey]"
  )) {
    for (const name of ["accesskey", "buttonaccesskey", "secondarybuttonaccesskey"]) {
      const k = el.getAttribute(name);
      if (k) {
        keys.push(k.toLowerCase());
      }
    }
  }
  return keys;
}

function guard(win, style, { escape, focusTarget }) {
  const panel = win.PopupNotifications.panel;
  let released = false;
  const release = () => {
    if (released) {
      return;
    }
    released = true;
    try {
      win.removeEventListener("keydown", onKeyDown, true);
      panel.removeEventListener("focusin", onFocusIn, true);
    } catch {
      // The window is gone.
    }
  };
  function onKeyDown(e) {
    if (!style.isConnected) {
      release();
      return;
    }
    if (e.key === "Escape" || e.keyCode === e.DOM_VK_ESCAPE) {
      e.preventDefault();
      e.stopPropagation();
      try {
        escape(e);
      } catch (err) {
        console.error(`[zen-share-picker] escape failed: ${err?.name ?? "error"}`);
      }
      return;
    }
    if (isAccessChord(e)) {
      e.preventDefault();
      e.stopPropagation();
    }
  }
  // P47: a chord of the chrome access-key modifiers and a key that is an
  // access key in the hidden panel would press that button (Allow, Block).
  // Gecko handles access keys on the keypress (EventStateManager
  // PreHandleEvent, or the reply from a remote page), and the widget sends
  // no keypress for a cancelled keydown, so cancelling the keydown is enough.
  const access = chromeAccessMask();
  function isAccessChord(e) {
    if (access <= 0) {
      return false;
    }
    const held =
      (e.shiftKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.altKey ? 4 : 0) | (e.metaKey ? 8 : 0);
    if ((held & access) !== access) {
      return false;
    }
    const pressed = new Set();
    if (typeof e.key === "string" && e.key.length === 1) {
      pressed.add(e.key.toLowerCase());
    }
    const code = /^(?:Key|Digit)(.)$/.exec(e.code ?? "");
    if (code) {
      pressed.add(code[1].toLowerCase());
    }
    if (!pressed.size) {
      return false;
    }
    try {
      return accessKeysOf(panel).some(k => pressed.has(k));
    } catch {
      // Unreadable panel: take any such chord as one.
      return true;
    }
  }
  function onFocusIn() {
    if (!style.isConnected) {
      release();
      return;
    }
    try {
      focusTarget()?.focus();
    } catch {
      // Cleared below.
    }
    try {
      if (inside(Services.focus.focusedElement, panel)) {
        Services.focus.clearFocus(win);
      }
    } catch {
      // Nothing else to try.
    }
  }
  win.addEventListener("keydown", onKeyDown, true);
  panel.addEventListener("focusin", onFocusIn, true);
  return release;
}

// Appends one hiding element, with its Esc and focus guards. `escape(event)`
// gets each Escape keydown while it is in the window; `focusTarget()` says
// where focus that enters the panel goes. Throws when it cannot. restore()
// removes only that element and its guards, as often as it is called, and
// never throws.
export function concealPanel(
  win,
  { escape = () => {}, focusTarget = () => win.gBrowser.selectedBrowser } = {}
) {
  const doc = win.document;
  const style = doc.createElementNS(HTML, "style");
  style.setAttribute(MARKER, "");
  style.textContent = RULE;
  doc.documentElement.append(style);
  let release;
  try {
    release = guard(win, style, { escape, focusTarget });
  } catch (e) {
    style.remove();
    throw e;
  }
  style[RELEASE] = release;
  return {
    restore() {
      release();
      try {
        style.remove();
      } catch {
        // Nothing left to remove, or the window is gone.
      }
      releaseAnchor(win);
    },
  };
}

// Removes every hiding element in the window, with its guards, the
// add-on's own `nonnative` (P48) and its own `no-open-on-anchor` (P67). Returns how many elements it removed; 0
// when the window cannot be read. Never throws.
export function revealPanel(win) {
  try {
    restoreNative(win.PopupNotifications.panel);
  } catch {
    // No panel to restore.
  }
  releaseAnchor(win);
  let found;
  try {
    found = Array.from(win.document.querySelectorAll(`[${MARKER}]`));
  } catch {
    return 0;
  }
  let removed = 0;
  for (const el of found) {
    try {
      el[RELEASE]?.();
    } catch {
      // Its listeners remove themselves once the element is gone.
    }
    try {
      el.remove();
      removed++;
    } catch {
      // The next one may still go.
    }
  }
  return removed;
}

// Whether the panel shows at least one notification, and every one it
// shows is `elementId`.
export function showsOnly(panel, elementId) {
  const shown = Array.from(panel.children).filter(c => !c.hidden);
  return shown.length > 0 && shown.every(c => c.id === elementId);
}
