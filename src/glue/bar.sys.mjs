// Restyles Firefox's sharing bar, the global sharing indicator, in place
// (P75, P77).
//
// The sheet goes in through the window's author sheets at the bar's
// DOMContentLoaded, before Firefox's `load` handler sizes and shows it
// (test_sharing_bar_takes_an_injected_sheet, S11). Its rules apply only
// under MARK, so a sheet left behind changes nothing. Updates are followed
// by wrapping the window's `updateIndicatorState`, which webrtcUI calls on
// every change (test_sharing_bar_update_hook, S12); Firefox's own calls at
// `load` and `sizemodechange` bypass it, so the add-on listens to both.
// The wrapper runs Firefox's update first and in full. Off macOS the bar
// stays stock (P86).
//
// Every failure leaves the stock bar and reports a code (P80). The window
// is never closed: if anything but webrtcUI closes it, every screen share
// stops. Labels hold the share type and the requesting page's host only,
// never a title (P81).
//
// Placement (P73): after every update the bar sits at the bottom center of
// the content area of the window holding the latest share, 88px up when
// that share's tab is selected there and 16px otherwise (no split view
// detection, P83), and again on that window's tab switches and resizes,
// clamped into the available rect of that window's screen.
// Firefox clamps the bar onto the screen its window reports on every
// update, which on several displays is not where it sits, so a position
// change can't tell a user's drag from Firefox's moves. A drag is a move
// while a trusted press on the bar outside its buttons is armed, outside
// Firefox's updates and the add-on's own moves and resizes (P79); after one
// the add-on never moves that bar again.
//
// Hide (P74, P78) hides the window as Firefox's own setVisibility(false)
// does and remembers the shares running then. Firefox shows the bar on
// every update; right after it, in the same task, the add-on hides it again
// unless a share not remembered started and Firefox's update just set
// `visible` to "true". Shares that ended are forgotten on every update, so
// one that starts again counts as new. Shutdown leaves the visibility to
// Firefox's last update.

import {
  GAP_OTHER,
  GAP_SELECTED,
  accentTokens,
  barLabel,
  barPosition,
  hasNewShare,
  isUserMove,
  labelMaxPx,
  parseRgb,
  pruneKeys,
  shareKeys,
  topCenter,
} from "../lib/bar.mjs";

const HTML = "http://www.w3.org/1999/xhtml";

export const INDICATOR_URL = "chrome://browser/content/webrtcIndicator.xhtml";
export const INDICATOR_TYPE = "Browser:WebRTCGlobalIndicator";
export const MARK = "data-zen-share-picker-bar";
export const REQUIRED_IDS = [
  "display-share",
  "display-share-icon",
  "stop-sharing",
  "drag-indicator",
  "device-share",
  "window-controls",
  "window-share-info",
  "browser-window-share-info",
  "screen-share-info",
];

const SHAPE = "data-zm-shape";
// Set while the add-on hides the bar; "opacity" also sets the window's
// opacity to 0 through the sheet (BAR_HIDE_OPACITY, P82).
const HIDDEN = "data-zm-hidden";
const LABEL_ID = "zm-share-label";
const HIDE_ID = "zm-hide";
const STOP_L10N = "webrtc-stop-sharing-button";
const STOP_TEXT = "Stop sharing";
const MUTE_PREF = "privacy.webrtc.globalMuteToggles";
const ACCENT_PREF = "zen.theme.accent-color";
const SYSTEM_ACCENT = "AccentColor";
// accentTokens field -> custom property on the bar's root.
const TOKENS = {
  accent: "--zm-accent",
  fill: "--zm-fill",
  fillHover: "--zm-fill-hover",
  fillPressed: "--zm-fill-pressed",
  fillText: "--zm-fill-text",
  tint: "--zm-tint",
  tintHover: "--zm-tint-hover",
  tintPressed: "--zm-tint-pressed",
  ink: "--zm-ink",
  inkStrong: "--zm-ink-strong",
};
const LABEL_MAX = "--zm-label-max";
// The transparent margin around the pill, which Firefox's resize counts.
const MARGIN = 6;
// How long a press stays armed after its mouseup, for a move that reaches
// Gecko just after the drop.
const DISARM_MS = 250;

// Calls onBar(win) for every sharing bar, open now or later, once its
// document is there; onBar returns the bar's uninstall, which runs when the
// bar unloads or on stop(). A throwing onBar or uninstall is caught, so one
// bar never stops the others.
export function watchBars({ Services, onBar }) {
  // win -> { uninstall, onUnload }
  const installed = new Map();
  // Windows opened since, waiting for their document: win -> listener.
  const pending = new Map();
  let stopped = false;

  function undo(win) {
    const entry = installed.get(win);
    if (!entry) {
      return;
    }
    installed.delete(win);
    try {
      win.removeEventListener("unload", entry.onUnload);
    } catch {
      // The window is gone.
    }
    try {
      entry.uninstall();
    } catch (e) {
      console.error(`[zen-share-picker] bar uninstall failed: ${e?.name ?? "error"}`);
    }
  }

  function watch(win) {
    if (stopped || installed.has(win) || win.closed) {
      return;
    }
    if (win.document?.documentURI !== INDICATOR_URL) {
      return;
    }
    let uninstall;
    try {
      uninstall = onBar(win);
    } catch (e) {
      console.error(`[zen-share-picker] bar install failed: ${e?.name ?? "error"}`);
      return;
    }
    const onUnload = () => undo(win);
    installed.set(win, {
      uninstall: typeof uninstall === "function" ? uninstall : () => {},
      onUnload,
    });
    win.addEventListener("unload", onUnload, { once: true });
  }

  // Waits for the window's first document past about:blank.
  function whenReady(win) {
    if (pending.has(win)) {
      return;
    }
    const onReady = () => {
      const uri = win.document?.documentURI;
      if (uri === "about:blank") {
        return;
      }
      win.removeEventListener("DOMContentLoaded", onReady, true);
      pending.delete(win);
      watch(win);
    };
    pending.set(win, onReady);
    win.addEventListener("DOMContentLoaded", onReady, true);
  }

  const observer = {
    observe(win, topic) {
      if (topic === "domwindowopened" && !stopped) {
        whenReady(win);
      }
    },
  };
  Services.ww.registerNotification(observer);
  for (const win of Services.wm.getEnumerator(INDICATOR_TYPE)) {
    if (win.document?.readyState === "loading") {
      whenReady(win);
    } else {
      watch(win);
    }
  }

  return {
    stop() {
      if (stopped) {
        return;
      }
      stopped = true;
      Services.ww.unregisterNotification(observer);
      for (const [win, onReady] of pending) {
        try {
          win.removeEventListener("DOMContentLoaded", onReady, true);
        } catch {
          // The window is gone.
        }
      }
      pending.clear();
      for (const win of [...installed.keys()]) {
        undo(win);
      }
    },
  };
}

// Removes what an earlier version may have left on the bar: its elements,
// its sheet, its wrapper and its markers. True when it found a MARK.
function clearLeftovers(win) {
  const doc = win.document;
  const root = doc.documentElement;
  const fn = win.updateIndicatorState;
  if (fn?.zspWrapped && typeof fn.zspOriginal === "function") {
    win.updateIndicatorState = fn.zspOriginal;
  }
  if (!root.hasAttribute(MARK)) {
    return false;
  }
  for (const id of [LABEL_ID, HIDE_ID]) {
    for (const el of doc.querySelectorAll(`#${id}`)) {
      el.remove();
    }
  }
  try {
    win.windowUtils.removeSheetUsingURIString(
      root.getAttribute(MARK),
      win.windowUtils.AUTHOR_SHEET
    );
  } catch {
    // Not a sheet URL, or not loaded.
  }
  doc.getElementById("stop-sharing")?.setAttribute("data-l10n-id", STOP_L10N);
  for (const prop of [...Object.values(TOKENS), LABEL_MAX]) {
    root.style.removeProperty(prop);
  }
  root.removeAttribute(SHAPE);
  root.removeAttribute(HIDDEN);
  root.removeAttribute(MARK);
  return true;
}

function knownMarkup(win) {
  const doc = win.document;
  return (
    doc.documentElement.id === "webrtcIndicator" &&
    REQUIRED_IDS.every((id) => doc.getElementById(id)) &&
    typeof win.updateIndicatorState === "function"
  );
}

// Asks Fluent for Firefox's own text again. Never throws.
function retranslate(win, el) {
  try {
    win.document.l10n?.translateElements([el])?.catch?.(() => {});
  } catch {
    // The bar keeps the text it has.
  }
}

// The accent as [r, g, b]: the pref's color, or the system accent when the
// pref is not a color, as the bar's document computes it.
function accentOf(win, Services) {
  let value = SYSTEM_ACCENT;
  try {
    value = Services.prefs.getStringPref(ACCENT_PREF, SYSTEM_ACCENT);
  } catch {
    value = SYSTEM_ACCENT;
  }
  const doc = win.document;
  const probe = doc.createElementNS(HTML, "span");
  probe.style.display = "none";
  probe.style.color = value;
  if (!probe.style.color) {
    probe.style.color = SYSTEM_ACCENT;
  }
  doc.documentElement.append(probe);
  try {
    let rgb = parseRgb(win.getComputedStyle(probe).color);
    if (!rgb) {
      probe.style.color = SYSTEM_ACCENT;
      rgb = parseRgb(win.getComputedStyle(probe).color);
    }
    if (!rgb) {
      throw new Error("no accent");
    }
    return rgb;
  } finally {
    probe.remove();
  }
}

// The latest share's browser and its window, or null: the browser Firefox
// itself centers the bar on.
function anchorOf(webrtcUI) {
  const streams = webrtcUI.getActiveStreams(true, true, true, true, true);
  const browser = streams[streams.length - 1]?.browser;
  const owner = browser?.documentGlobal;
  if (!owner?.gBrowser || owner.closed) {
    return null;
  }
  return { browser, owner };
}

// The screen rect of `browser` in `owner`, or null when it has no size.
function screenRect(owner, browser) {
  const r = owner.windowUtils.getBoundsWithoutFlushing(browser);
  if (!(r.width > 0 && r.height > 0)) {
    return null;
  }
  return {
    x: owner.mozInnerScreenX + r.left,
    y: owner.mozInnerScreenY + r.top,
    width: r.width,
    height: r.height,
  };
}

// The content area of the anchor window, or null.
function contentOf({ owner }) {
  return screenRect(owner, owner.gBrowser.selectedBrowser);
}

// The available rect of the anchor window's screen, which the bar stays
// inside. The bar's own `screen` is not reliable on a second display.
function screenOf(owner) {
  const s = owner.screen;
  return { left: s.availLeft, top: s.availTop, width: s.availWidth, height: s.availHeight };
}

// The content width of the window holding the latest share, or null.
function anchorWidth(webrtcUI) {
  try {
    const anchor = anchorOf(webrtcUI);
    return anchor ? (contentOf(anchor)?.width ?? null) : null;
  } catch {
    return null;
  }
}

// Restyles one bar. Returns its handle, or null when the bar stays stock:
// off macOS or with the mute toggles on (choices, not problems, P86), with
// markup it does not know, or when the restyle throws (each undone first).
export function restyleBar(
  win,
  { Services, webrtcUI, cssUrl, shape, hideOpacity = false, record, problem }
) {
  if (Services.appinfo.OS !== "Darwin") {
    record("bar stock platform");
    return null;
  }
  if (Services.prefs.getBoolPref(MUTE_PREF, false)) {
    record("bar stock mute-toggles");
    return null;
  }
  const doc = win.document;
  const root = doc.documentElement;
  const cleared = clearLeftovers(win);
  if (!knownMarkup(win)) {
    if (cleared) {
      retranslate(win, doc.getElementById("stop-sharing"));
    }
    problem("bar-unknown-markup");
    return null;
  }
  const utils = win.windowUtils;
  const display = doc.getElementById("display-share");
  const icon = doc.getElementById("display-share-icon");
  const stop = doc.getElementById("stop-sharing");

  let released = false;
  let sheet = false;
  let label = null;
  let verb = null;
  let site = null;
  let hide = null;
  let original = null;
  let wrapped = null;
  let listening = false;
  // Placement: whether the add-on ever moved the bar, the last position it
  // set, whether the user dragged it, and the last gap logged.
  let moved = false;
  let lastSet = null;
  let dragged = false;
  let lastGap = null;
  // Set while Firefox's update or the add-on's own move or resize runs:
  // moves then are never the user's.
  let inUpdate = false;
  let moving = false;
  // A trusted press on the bar outside its buttons, until its mouseup plus
  // DISARM_MS or the add-on's next move.
  let armed = false;
  let disarmTimer = null;
  let loadPending = false;
  // The anchor window holding the TabSelect and resize listeners.
  let anchorWin = null;
  let anchorTabs = null;
  // Set as the bar unloads: Firefox's update must not run on it then (its
  // unload handler already took its menu bar items down).
  let gone = false;
  const onUnload = () => {
    gone = true;
  };
  // Hide (P74, P78): whether the add-on hides the bar, and the shares
  // running at Hide that are still running.
  let hidden = false;
  let remembered = new Set();
  // The bar's color scheme: a change refreshes the accent tokens.
  let scheme = null;
  const onScheme = () => update();

  // Firefox's own updates at `load` and `sizemodechange` bypass the wrapper.
  // Capturing listeners on the window run before Firefox's, at the target,
  // so they bracket those updates; the add-on's bubbling ones, after
  // Firefox's, end the bracket.
  const onUpdateStart = (event) => {
    if (event.type === "load" ? loadPending && event.target === doc : listening) {
      inUpdate = true;
    }
  };
  const onSizeMode = () => {
    inUpdate = false;
    afterFirefox();
    if (win.windowState !== win.STATE_MINIMIZED) {
      update();
    }
  };
  // Firefox adds its sizemodechange listener in its `load` handler, so ours
  // goes in after that and runs after Firefox's update.
  function listenSizeMode() {
    win.addEventListener("sizemodechange", onSizeMode);
    listening = true;
  }
  const onLoad = () => {
    inUpdate = false;
    loadPending = false;
    afterFirefox();
    listenSizeMode();
    update();
  };

  function disarm() {
    armed = false;
    if (disarmTimer !== null) {
      try {
        win.clearTimeout(disarmTimer);
      } catch {
        // The window is gone.
      }
      disarmTimer = null;
    }
  }
  const onPress = (event) => {
    if (event.isTrusted && event.button === 0 && !event.target?.closest?.("button")) {
      disarm();
      armed = true;
    }
  };
  const onRelease = (event) => {
    if (armed && event.isTrusted && event.button === 0 && disarmTimer === null) {
      disarmTimer = win.setTimeout(disarm, DISARM_MS);
    }
  };
  // P79: Firefox's moves (its clamp onto the screen in every update) run
  // inside an update, the add-on's inside its own move or resize, and
  // neither comes with an armed press.
  const onWindowPos = () => {
    if (dragged || released || inUpdate || moving || !armed) {
      return;
    }
    if (lastSet && !isUserMove(lastSet, { x: win.screenX, y: win.screenY })) {
      return;
    }
    dragged = true;
    unbind();
    record("bar dragged");
  };
  // The anchor's layout is stale in its own resize and TabSelect events, so
  // the bar follows once that window has laid out again.
  const onAnchorChange = (event) => {
    const owner = event.currentTarget?.ownerGlobal ?? event.currentTarget;
    try {
      owner
        .promiseDocumentFlushed(() => {})
        .then(relayout, () => {})
        .catch(() => {});
    } catch {
      relayout();
    }
  };
  const onAnchorUnload = () => unbind();
  const onHideClick = (event) => {
    if (event.isTrusted) {
      hideBar();
    }
  };

  function bind(owner) {
    if (owner === anchorWin) {
      return;
    }
    unbind();
    const tabs = owner.gBrowser.tabContainer;
    tabs.addEventListener("TabSelect", onAnchorChange);
    owner.addEventListener("resize", onAnchorChange);
    owner.addEventListener("unload", onAnchorUnload, { once: true });
    anchorWin = owner;
    anchorTabs = tabs;
  }

  function unbind() {
    const owner = anchorWin;
    const tabs = anchorTabs;
    anchorWin = null;
    anchorTabs = null;
    if (!owner) {
      return;
    }
    const steps = [
      () => tabs?.removeEventListener("TabSelect", onAnchorChange),
      () => owner.removeEventListener("resize", onAnchorChange),
      () => owner.removeEventListener("unload", onAnchorUnload),
    ];
    for (const step of steps) {
      try {
        step();
      } catch {
        // The window is gone.
      }
    }
  }

  function moveTo({ x, y }) {
    disarm();
    moving = true;
    try {
      win.moveTo(x, y);
    } finally {
      moving = false;
    }
  }

  // What Firefox's update does to size the bar (webrtcIndicator.js), for a
  // label or label limit the add-on changed after that update.
  function fit() {
    if (doc.readyState !== "complete" || win.windowState === win.STATE_MINIMIZED) {
      return;
    }
    const s = root.style;
    s.minWidth = s.maxWidth = "unset";
    s.minHeight = s.maxHeight = "unset";
    // sizeToContent can move the window too.
    moving = true;
    try {
      win.sizeToContent();
    } finally {
      moving = false;
    }
    if (Services.appinfo.OS === "Linux") {
      const { width, height } = utils.getBoundsWithoutFlushing(root);
      s.minWidth = s.maxWidth = `${width}px`;
      s.minHeight = s.maxHeight = `${height}px`;
    }
  }

  // Moves the bar to its spot over the anchor's content area, unless the
  // user dragged it. Never throws: a bar it can't place waits for the next
  // update.
  function place() {
    if (released || dragged || gone || win.closed) {
      return;
    }
    try {
      const anchor = anchorOf(webrtcUI);
      if (!anchor) {
        unbind();
        return;
      }
      bind(anchor.owner);
      const content = contentOf(anchor);
      if (!content) {
        return;
      }
      const selected = anchor.owner.gBrowser.selectedBrowser === anchor.browser;
      const { width, height } = utils.getBoundsWithoutFlushing(root);
      const pos = barPosition({
        content,
        size: { width, height },
        selected,
        margin: MARGIN,
        screen: screenOf(anchor.owner),
      });
      if (win.screenX !== pos.x || win.screenY !== pos.y) {
        moveTo(pos);
        moved = true;
      }
      lastSet = pos;
      const gap = selected ? GAP_SELECTED : GAP_OTHER;
      if (gap !== lastGap) {
        lastGap = gap;
        record(`bar placed ${gap}`);
      }
    } catch {
      // Placed again on the next update.
    }
  }

  // The label's text and limit, which set the bar's width.
  function widthKey() {
    return `${verb.textContent}|${site.textContent}|${root.style.getPropertyValue(LABEL_MAX)}`;
  }

  function setLabelMax() {
    const width = anchorWidth(webrtcUI);
    if (width) {
      root.style.setProperty(LABEL_MAX, `${labelMaxPx(width)}px`);
    } else {
      root.style.removeProperty(LABEL_MAX);
    }
  }

  // The anchor window switched tabs or resized.
  function relayout() {
    if (released || gone || win.closed) {
      return;
    }
    try {
      const before = widthKey();
      setLabelMax();
      if (widthKey() !== before) {
        fit();
      }
    } catch {
      // The label keeps its limit until the next update.
    }
    place();
  }

  // Firefox's top-center spot over the latest share's browser, as its
  // centerOnLatestBrowser computes it, or null.
  function homeSpot() {
    try {
      const anchor = anchorOf(webrtcUI);
      if (!anchor) {
        return null;
      }
      const content = screenRect(anchor.owner, anchor.browser) ?? contentOf(anchor);
      if (!content) {
        return null;
      }
      const { width, height } = utils.getBoundsWithoutFlushing(root);
      return topCenter({ content, size: { width, height } });
    } catch {
      return null;
    }
  }

  // Undoes every change, each step on its own. Never throws.
  function undo() {
    const steps = [
      () => {
        if (wrapped && win.updateIndicatorState === wrapped) {
          win.updateIndicatorState = original;
        }
      },
      () => win.removeEventListener("load", onLoad),
      () => win.removeEventListener("unload", onUnload),
      () => listening && win.removeEventListener("sizemodechange", onSizeMode),
      () => win.removeEventListener("load", onUpdateStart, true),
      () => win.removeEventListener("sizemodechange", onUpdateStart, true),
      () => win.removeEventListener("mousedown", onPress, true),
      () => win.removeEventListener("mouseup", onRelease, true),
      () => disarm(),
      () => win.windowRoot?.removeEventListener("MozUpdateWindowPos", onWindowPos),
      () => scheme?.removeEventListener("change", onScheme),
      () => unbind(),
      () => sheet && utils.removeSheetUsingURIString(cssUrl, utils.AUTHOR_SHEET),
      () => label?.remove(),
      () => hide?.removeEventListener("click", onHideClick),
      () => hide?.remove(),
      () => {
        for (const prop of [...Object.values(TOKENS), LABEL_MAX]) {
          root.style.removeProperty(prop);
        }
      },
      () => root.removeAttribute(SHAPE),
      () => root.removeAttribute(HIDDEN),
      () => root.removeAttribute(MARK),
      () => {
        if (!stop.hasAttribute("data-l10n-id")) {
          stop.setAttribute("data-l10n-id", STOP_L10N);
          retranslate(win, stop);
        }
      },
    ];
    for (const step of steps) {
      try {
        step();
      } catch {
        // The next step still runs.
      }
    }
  }

  // Back to the stock bar, then Firefox's own update once, so its
  // attributes, size and visibility are its own again: a bar the add-on
  // hid shows unless Firefox's own prefs hide it.
  function release() {
    if (released) {
      return;
    }
    released = true;
    hidden = false;
    remembered = new Set();
    undo();
    // Firefox stops centering the bar once anything else moved it, so a
    // bar the add-on moved and the user never dragged goes back to
    // Firefox's spot: before Firefox's update, which clamps it onto the
    // screen, and once more after it if the stock size moved the center.
    const home = moved && !dragged && !gone && !win.closed;
    const spot = home ? homeSpot() : null;
    try {
      if (spot) {
        moveTo(spot);
      }
    } catch {
      // The bar stays where it is.
    }
    try {
      if (!gone && !win.closed) {
        win.updateIndicatorState();
      }
    } catch {
      // Firefox's update failed on its own.
    }
    const again = home && !win.closed ? homeSpot() : null;
    try {
      if (again && (!spot || again.x !== spot.x || again.y !== spot.y)) {
        moveTo(again);
      }
    } catch {
      // The bar stays where it is.
    }
  }

  // The screen, window and tab shares, keyed by their browser.
  function currentStreams() {
    return webrtcUI.getActiveStreams(false, false, true, true, true).map((s) => ({
      id: String(s.browser?.browserId ?? ""),
      uri: s.uri,
      devices: (s.devices ?? []).map((d) => ({ mediaSource: d.mediaSource, scary: d.scary })),
    }));
  }

  // What Firefox's setVisibility does (webrtcIndicator.js), so its menu bar
  // item keeps a hidden bar hidden.
  function setVisibility(visible) {
    win.docShell.treeOwner.QueryInterface(win.Ci.nsIBaseWindow).visibility = visible;
    root.setAttribute("visible", String(visible));
  }

  function hideBar() {
    if (released || gone || win.closed) {
      return;
    }
    // Without Firefox's `visible` the add-on could never tell a new share
    // should bring the bar back, so it doesn't hide it.
    if (!root.hasAttribute("visible")) {
      record("bar hide refused");
      return;
    }
    try {
      remembered = shareKeys(currentStreams());
      hidden = true;
      root.setAttribute(HIDDEN, hideOpacity ? "opacity" : "");
      setVisibility(false);
      record(`bar hidden ${remembered.size} shares`);
    } catch {
      // The bar stays as it is.
    }
  }

  // Right after each of Firefox's updates, in the same task: Firefox just
  // set `visible` as it wants it. A share not running at Hide brings back
  // a bar Firefox wants shown; anything else hides it again, before a frame
  // can show it. Never shows a bar Firefox did not just show.
  function afterFirefox() {
    if (!hidden || released || gone || win.closed) {
      return;
    }
    try {
      const wanted = root.getAttribute("visible") === "true";
      const current = shareKeys(currentStreams());
      const fresh = hasNewShare(remembered, current);
      remembered = pruneKeys(remembered, current);
      if (fresh && wanted) {
        hidden = false;
        remembered = new Set();
        root.removeAttribute(HIDDEN);
        setVisibility(true);
        record("bar shown new-share");
        return;
      }
    } catch {
      // Hidden again below.
    }
    try {
      setVisibility(false);
    } catch {
      // The bar shows until the next update.
    }
  }

  function render() {
    const streams = currentStreams();
    const text = barLabel(streams);
    verb.textContent = text.site ? `${text.verb} ` : text.verb;
    site.textContent = text.site;
    site.hidden = !text.site;
    if (text.text) {
      label.setAttribute("aria-label", text.text);
    } else {
      label.removeAttribute("aria-label");
    }
    display.setAttribute("aria-labelledby", LABEL_ID);
    if (stop.textContent !== STOP_TEXT) {
      stop.textContent = STOP_TEXT;
    }
    setLabelMax();
    const dark = win.matchMedia("(prefers-color-scheme: dark)").matches;
    const tokens = accentTokens(accentOf(win, Services), dark);
    for (const [key, prop] of Object.entries(TOKENS)) {
      root.style.setProperty(prop, tokens[key]);
    }
  }

  function update() {
    if (released) {
      return;
    }
    try {
      const before = widthKey();
      render();
      // Firefox's update sized the bar for the label it had before.
      if (widthKey() !== before) {
        fit();
      }
    } catch {
      release();
      problem("bar-internal");
      return;
    }
    place();
  }

  try {
    win.addEventListener("unload", onUnload, { once: true });
    utils.loadSheetUsingURIString(cssUrl, utils.AUTHOR_SHEET);
    sheet = true;
    root.setAttribute(MARK, cssUrl);
    root.setAttribute(SHAPE, shape);

    label = doc.createElementNS(HTML, "span");
    label.id = LABEL_ID;
    label.className = "zm-share-label";
    verb = doc.createElementNS(HTML, "span");
    verb.className = "zm-verb";
    site = doc.createElementNS(HTML, "span");
    site.className = "zm-site";
    label.append(verb, site);
    icon.after(label);

    hide = doc.createElementNS(HTML, "button");
    hide.id = HIDE_ID;
    hide.className = "zm-hide";
    hide.type = "button";
    hide.textContent = "Hide";
    hide.addEventListener("click", onHideClick);
    stop.before(hide);

    stop.removeAttribute("data-l10n-id");
    stop.textContent = STOP_TEXT;

    original = win.updateIndicatorState;
    wrapped = function (...args) {
      inUpdate = true;
      try {
        return original.apply(this, args);
      } finally {
        inUpdate = false;
        afterFirefox();
        update();
      }
    };
    wrapped.zspWrapped = true;
    wrapped.zspOriginal = original;
    win.updateIndicatorState = wrapped;
    win.addEventListener("mousedown", onPress, true);
    win.addEventListener("mouseup", onRelease, true);
    win.addEventListener("load", onUpdateStart, true);
    win.addEventListener("sizemodechange", onUpdateStart, true);
    win.windowRoot.addEventListener("MozUpdateWindowPos", onWindowPos);
    scheme = win.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", onScheme);

    if (doc.readyState === "complete") {
      listenSizeMode();
    } else {
      loadPending = true;
      win.addEventListener("load", onLoad, { once: true });
    }
  } catch {
    released = true;
    undo();
    try {
      if (doc.readyState === "complete" && !win.closed) {
        win.updateIndicatorState();
      }
    } catch {
      // Firefox's update failed on its own.
    }
    problem("bar-style-failed");
    return null;
  }

  // A bar that is already showing gets Firefox's update, which sizes it to
  // the sheet; one still loading gets it from Firefox's `load` handler.
  if (doc.readyState === "complete") {
    try {
      win.updateIndicatorState();
    } catch {
      // Firefox's update failed on its own; ours still ran.
    }
  } else {
    update();
  }
  if (released) {
    return null;
  }
  return { update, release, hide: hideBar, isHidden: () => hidden };
}
