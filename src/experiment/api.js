// Parent-process side of the add-on. This ext-*.js sandbox has no URL
// constructor (gre/modules/ExtensionCommon.sys.mjs:1823-1866), so the logic
// lives in modules loaded through resource://zen-share-picker-<version>/,
// which maps to the add-on root. Those modules keep no state of their own:
// all of it lives here, so a disable and re-enable starts clean.

/* globals ExtensionAPI, ChromeUtils, Services, Cc, Ci */
"use strict";

const NAME = "zen-share-picker";
// Modules stay cached per URL for the life of the process, so each version
// gets its own resource host and an in-place update loads its own modules.
const hostFor = version => `${NAME}-${String(version).replace(/[^A-Za-z0-9]/g, "-")}`;
const MODULES = {
  arming: "src/lib/arming.mjs",
  config: "src/lib/config.mjs",
  rows: "src/lib/rows.mjs",
  captures: "src/lib/captures.mjs",
  share: "src/lib/share.mjs",
  decline: "src/lib/decline.mjs",
  prompt: "src/glue/prompt.sys.mjs",
  tabs: "src/glue/tabs.sys.mjs",
  overlay: "src/glue/overlay.sys.mjs",
  watch: "src/glue/watch.sys.mjs",
  selfcheck: "src/glue/selfcheck.sys.mjs",
  conceal: "src/glue/conceal.sys.mjs",
  windows: "src/glue/windows.sys.mjs",
};
const CSS = "src/glue/picker.css";
// Firefox internals; the startup checks cover both.
const INTERNALS = {
  webrtcUI: ["resource:///modules/webrtcUI.sys.mjs", "webrtcUI"],
  PageThumbs: ["resource://gre/modules/PageThumbs.sys.mjs", "PageThumbs"],
};
// The stock screen-share notification (WebRTCParent.sys.mjs).
const PROMPT_ID = "webRTC-shareDevices";
const DELAY_PREF = "security.notification_enable_delay";
// Zen's own switch for its prompt's previews (WebRTCParent.sys.mjs).
const PREVIEWS_PREF = "media.getdisplaymedia.previews.enabled";
// Prompts the picker has nothing to offer for; not problems.
const SILENT = new Set(["not-screen-request", "mixed-request"]);
const MAX_PROBLEMS = 10;
// P64 (c): the longest a hiding taken in popupshowing waits for a picker.
const EARLY_HIDE_MS = 3000;
const LOG_LIMIT = 2000;

// The one shape of the status, for a running add-on and for one that shut down.
const statusOf = ({
  version,
  state,
  failedChecks = [],
  promptProblems = [],
  shareMode = "",
  previewMode = "",
  lastOutcome = null,
  debug = false,
}) => ({
  state,
  failedChecks: [...failedChecks],
  promptProblems: [...promptProblems],
  shareMode,
  previewMode,
  lastOutcome,
  debug,
  version,
});

const resProto = Cc["@mozilla.org/network/protocol;1?name=resource"].getService(
  Ci.nsISubstitutingProtocolHandler
);

// Reason codes only: never a title, URL, host or image.
const logError = code => console.error(`[${NAME}] ${code}`);

// Every tab of a window, in every space: gBrowser.tabs holds only the active
// space's tabs in Zen.
function tabsOf(win) {
  const tabs = new Set(win.gBrowser?.tabs ?? []);
  for (const t of win.gZenWorkspaces?.allStoredTabs ?? []) {
    tabs.add(t);
  }
  return tabs;
}

//   starting -> active   the modules loaded and the first browser window
//                        passed the startup checks
//   starting -> inert    a module did not load ("modules") or a check failed
//   active, inert -> disabled   setEnabled(false) closes every picker
//   disabled, inert -> starting setEnabled(true) runs the checks again
//   any      -> shut down  the add-on is disabled, removed or updated, or Zen quits
//
// setEnabled and setDebug last until Zen restarts: nothing is stored, and
// no pref is written. The debug log is in memory, holds at most LOG_LIMIT
// lines, is empty while debug is off, and never holds a title or an image.
// It holds the hosts of this space's rows when a picker opens, and another
// space's hosts only once Tab revealed them.
//
// Per window, a PanelUpdated for the share prompt opens the picker on the
// next tick (onPrompt). One open picker per window, in `sessions`. A prompt
// the user declined (`declined`), or that a share ran on (`sharing`), never
// gets a picker again. P52: a prompt gets a picker when it lists a tab or a
// screen or window row; Zen's own windows are never rows (P50). Esc and Cancel
// decline the request (P36, P38); every other close leaves it pending.
//
// P35: each session owns its hiding of Zen's panel (`conceal`). It hides
// the panel only once its picker is open and the panel shows the share
// prompt alone. The panel shows again when the session closes, when its
// share finds the prompt no longer current, and at the latest when its
// share or decline settles. P43: it also shows again, for good, when
// another notification joins the panel or the session's own one leaves.
// P44: while it is hidden, the session also owns Esc and keyboard focus in
// that window. Turning the picker off and shutdown sweep every window,
// whatever the sessions say, and install clears each window it watches.
class Picker {
  constructor(rootURI, version) {
    this.rootURI = rootURI;
    this.version = version;
    this.host = hostFor(version);
    this.state = "starting";
    this.failedChecks = [];
    this.promptProblems = [];
    this.lastOutcome = null;
    this.debug = false;
    this.log = [];
    // Bumped by setEnabled(false), so a share already running never clicks.
    this.generation = 0;
    this.toggling = Promise.resolve();
    this.m = null;
    this.startPromise = null;
    this.stopped = false;
    this.watcher = null;
    this.firstWindow = null;
    // win -> session; a session is one open picker.
    this.sessions = new Map();
    this.declined = new WeakSet();
    this.sharing = new WeakSet();
    // Sessions whose share is running; the panel may still be hidden.
    this.running = new Set();
    // P48: win -> {handle, holder}, a hiding taken in popupshowing, before
    // the picker opens; onPrompt adopts it or shows the panel again.
    this.early = new Map();
    // Notification -> the OS entry's deviceId (or null), from its first read.
    this.osIds = new WeakMap();
    // P70: notification -> the ids of Zen's windows seen at any of its reads.
    this.zenIds = new WeakMap();
    // Notifications whose Zen window ids could not be read, recorded once.
    this.idsUnknown = new WeakSet();
  }

  start() {
    this.startPromise ??= this.init().catch(e => this.fail("start", e));
    return this.startPromise;
  }

  // A debug log line: reason codes, counts, hosts and device ids only.
  record(line) {
    if (!this.debug) {
      return;
    }
    this.log.push(line);
    if (this.log.length > LOG_LIMIT) {
      this.log.splice(0, this.log.length - LOG_LIMIT);
    }
  }

  recordHosts(rows) {
    for (const row of rows) {
      this.record(`host ${row.host || "-"}`);
    }
  }

  fail(check, e) {
    logError(`check ${check} failed: ${e?.name ?? "error"}`);
    this.record(`check ${check} failed`);
    if (this.stopped) {
      return;
    }
    if (!this.failedChecks.includes(check)) {
      this.failedChecks.push(check);
    }
    this.state = "inert";
  }

  // A prompt that got no picker; the stock prompt is left as it is.
  problem(code) {
    logError(code);
    this.record(`problem ${code}`);
    this.promptProblems.push(code);
    this.promptProblems.splice(0, this.promptProblems.length - MAX_PROBLEMS);
  }

  internal(name) {
    const [url, key] = INTERNALS[name];
    return ChromeUtils.importESModule(url)[key];
  }

  async init() {
    resProto.setSubstitution(this.host, this.rootURI);
    const m = {};
    try {
      for (const [key, path] of Object.entries(MODULES)) {
        m[key] = ChromeUtils.importESModule(`resource://${this.host}/${path}`);
      }
    } catch (e) {
      this.fail("modules", e);
      return;
    }
    if (this.stopped) {
      return;
    }
    this.m = m;
    await this.watch();
  }

  // The state is settled by the first browser window's checks.
  watch() {
    return new Promise(resolve => {
      this.firstWindow = resolve;
      this.watcher = this.m.watch.watchWindows({
        Services,
        onWindow: win => this.onWindow(win),
      });
    });
  }

  stopWatching() {
    for (const win of [...this.early.keys()]) {
      this.revealEarly(win);
    }
    for (const session of [...this.sessions.values()]) {
      session.done = true;
      this.closeSession(session);
    }
    this.sessions.clear();
    try {
      this.watcher?.stop();
    } catch (e) {
      logError(`stop failed: ${e?.name ?? "error"}`);
    }
    this.watcher = null;
    this.revealEverywhere();
  }

  // Removes every hiding element in every browser window, with or without a
  // session behind it. Never throws.
  revealEverywhere() {
    const conceal = this.m?.conceal;
    if (!conceal) {
      return;
    }
    try {
      for (const w of Services.wm.getEnumerator("navigator:browser")) {
        conceal.revealPanel(w);
      }
    } catch (e) {
      logError(`reveal failed: ${e?.name ?? "error"}`);
    }
  }

  onWindow(win) {
    if (this.stopped) {
      return () => {};
    }
    if (this.state === "starting") {
      const failed = this.m.selfcheck.startupChecks(win, {
        ChromeUtils,
        previewMode: this.m.config.PREVIEW_MODE,
      });
      for (const code of failed) {
        logError(`check ${code} failed`);
        this.record(`check ${code} failed`);
        this.failedChecks.push(code);
      }
      this.state = failed.length ? "inert" : "active";
      this.firstWindow?.();
      this.firstWindow = null;
    }
    if (this.state !== "active") {
      return () => {};
    }
    return this.install(win);
  }

  // The window's listeners; returns their uninstall.
  install(win) {
    // P35: hiding elements an earlier version may have left.
    this.m.conceal.revealPanel(win);
    const panel = win.PopupNotifications.panel;
    const tabContainer = win.gBrowser.tabContainer;
    const onPanelUpdated = e => {
      if (e.target !== panel) {
        return;
      }
      let ids = [];
      try {
        ids = Array.from(e.detail ?? []);
      } catch {
        ids = [];
      }
      const others = ids.some(id => id !== PROMPT_ID);
      if (!ids.includes(PROMPT_ID)) {
        this.closeIn(win);
        this.revealGone(win, true);
        this.revealEarly(win);
        return;
      }
      // P43: another notification shares the panel, or a session's own
      // notification left it: show the panel, for good.
      this.revealGone(win, others);
      if (others) {
        this.revealEarly(win);
      }
      // Zen can update the open panel in place, with no popuphidden: a new
      // notification under the same id, or a rebuilt dropdown. A picker on
      // the old prompt closes, without declining it, and onPrompt opens a
      // fresh one. One deferred onPrompt per PanelUpdated.
      const session = this.sessions.get(win);
      if (session && !session.done && this.isStale(win, session)) {
        this.closeIn(win);
      }
      win.setTimeout(() => this.onPrompt(win), 0);
    };
    const onHidden = e => {
      if (e.target === panel) {
        this.closeIn(win);
        this.revealGone(win, true);
        this.revealEarly(win);
        this.m?.conceal.restoreNative(panel);
        this.m?.conceal.releaseAnchor(win);
      }
    };
    // P48: before the panel's first frame, for a prompt the picker will
    // take: a plain window, hidden.
    const onShowing = e => {
      if (e.target === panel) {
        this.onShowing(win);
      }
    };
    const onSelect = () => this.closeIn(win);
    const onTabGone = e => this.closeListing(e.target);
    // P33: the session's own activate time. Added before any picker opens,
    // so it runs before the overlay's listener and the session never arms
    // later than the overlay does.
    const onActivate = () => {
      const session = this.sessions.get(win);
      if (session) {
        session.times.activatedAt = ChromeUtils.now();
      }
    };
    // A space switch can keep the selected tab, an Essential the two spaces
    // share, and then fires no TabSelect. Zen calls its change listeners
    // once a switch ends (ZenSpaceManager.mjs addChangeListeners) and awaits
    // each, so this one never throws.
    const onSpaceChange = () => {
      try {
        this.closeIn(win);
      } catch (e) {
        logError(`close failed: ${e?.name ?? "error"}`);
      }
    };
    const spaces = win.gZenWorkspaces;
    spaces?.addChangeListeners?.(onSpaceChange);
    win.addEventListener("activate", onActivate, true);
    panel.addEventListener("PanelUpdated", onPanelUpdated);
    panel.addEventListener("popupshowing", onShowing, true);
    panel.addEventListener("popuphidden", onHidden);
    tabContainer.addEventListener("TabSelect", onSelect);
    // On the window: Essentials may live outside the tab container.
    win.addEventListener("TabClose", onTabGone, true);
    win.addEventListener("TabBrowserDiscarded", onTabGone, true);
    return () => {
      try {
        spaces?.removeChangeListeners?.(onSpaceChange);
      } catch (e) {
        logError(`stop failed: ${e?.name ?? "error"}`);
      }
      win.removeEventListener("activate", onActivate, true);
      panel.removeEventListener("PanelUpdated", onPanelUpdated);
      panel.removeEventListener("popupshowing", onShowing, true);
      panel.removeEventListener("popuphidden", onHidden);
      tabContainer.removeEventListener("TabSelect", onSelect);
      win.removeEventListener("TabClose", onTabGone, true);
      win.removeEventListener("TabBrowserDiscarded", onTabGone, true);
      this.closeIn(win);
      this.revealEarly(win);
      // A closed window's timers never fire, so its running shares would
      // never settle on their own.
      for (const session of [...this.running]) {
        if (session.win === win) {
          this.running.delete(session);
          this.reveal(session);
        }
      }
      this.m?.conceal.revealPanel(win);
    };
  }

  // P43: shows the panel for every session of `win` that hides it, the open
  // picker's and running shares', when `all` or when the panel no longer
  // shows that session's own notification.
  revealGone(win, all) {
    const open = this.sessions.get(win);
    for (const session of [...(open ? [open] : []), ...this.running]) {
      if (session.win !== win || !session.conceal) {
        continue;
      }
      let shown = false;
      try {
        shown =
          win.document.getElementById(this.m.prompt.IDS.element)?.notification ===
          session.info.notification;
      } catch {
        shown = false;
      }
      if (all || !shown) {
        this.reveal(session);
      }
    }
  }

  // Whether the session's prompt is no longer the one shown: another
  // notification object, or an entry item that left the dropdown.
  isStale(win, session) {
    try {
      const { IDS } = this.m.prompt;
      const doc = win.document;
      const { info } = session;
      if (doc.getElementById(IDS.element)?.notification !== info.notification) {
        return true;
      }
      const list = doc.getElementById(IDS.menulist);
      return !list || info.entries.some(e => e.item.parentNode?.parentNode !== list);
    } catch {
      return true;
    }
  }

  // P48: whether the panel about to show holds only a share prompt that
  // onPrompt would open a picker for, by the same rule (P52: a tab entry or
  // a screen or window row). WebRTC builds the dropdown in its
  // "showing" callback, and PopupNotifications fills the panel, before
  // openPopup (PopupNotifications.sys.mjs _showPanel), so this reads the same
  // prompt. Records nothing.
  handles(win) {
    if (this.stopped || this.state !== "active" || !this.m || this.sessions.has(win)) {
      return false;
    }
    try {
      const m = this.m;
      if (!m.conceal.showsOnly(win.PopupNotifications.panel, m.prompt.IDS.element)) {
        return false;
      }
      const read = m.prompt.readPrompt(win, { showing: true });
      if (!read.ok) {
        return false;
      }
      const n = read.info.notification;
      if (this.declined.has(n) || this.sharing.has(n)) {
        return false;
      }
      const info = { ...read.info, osEntry: this.osEntryOf(read.info, false) };
      if (!this.offersRows(info, this.capturesOf(info, false))) {
        return false;
      }
      return m.tabs.tabFacts(info.entries, win, info.browser, Services).ok;
    } catch {
      return false;
    }
  }

  // P17: the OS entry is the one Zen pre-selected when the prompt was
  // first shown. Zen rebuilds the dropdown each time the prompt shows
  // (WebRTCParent.sys.mjs listScreenShareDevices), so a later read finds
  // that entry again by its deviceId, never by the selection. `remember`
  // records the first read's; handles() records nothing.
  osEntryOf(info, remember) {
    const n = info.notification;
    if (!this.osIds.has(n)) {
      if (remember) {
        this.osIds.set(n, info.osEntry ? info.osEntry.deviceId : null);
      }
      return info.osEntry;
    }
    const id = this.osIds.get(n);
    return id === null
      ? null
      : (info.entries.find(e => e.deviceId === id && e.mediaSource !== "browser") ?? null);
  }

  // The screen and window rows of a prompt, without Zen's own windows (P50).
  // P70: a window seen as Zen's at any read of the prompt stays hidden, since
  // Zen lists the request's windows again on every show. `remember` records
  // this read's ids, and `zen-ids-unknown` once per prompt when they can't be
  // read and the prompt lists a window; handles() records nothing.
  capturesOf(info, remember) {
    const n = info.notification;
    const zen = this.m.windows.zenWindowIds(Services, this.zenIds.get(n) ?? null);
    if (remember && zen.ok) {
      this.zenIds.set(n, zen.ids);
    }
    if (
      remember &&
      !zen.ok &&
      !this.idsUnknown.has(n) &&
      info.entries.some(e => e.mediaSource === "window")
    ) {
      this.idsUnknown.add(n);
      this.problem("zen-ids-unknown");
    }
    return this.m.captures.captureRows(info.entries, info.osEntry?.deviceId ?? null, zen);
  }

  // P52: a picker only for a prompt with a tab entry or a capture row.
  offersRows(info, captures) {
    return captures.rows.length > 0 || info.entries.some(e => e.mediaSource === "browser");
  }

  // P48: makes the panel a plain window and hides it before it shows, for a
  // prompt the picker will take. onPrompt adopts the hiding, or shows the
  // panel again when it opens no picker.
  onShowing(win) {
    if (!this.handles(win)) {
      return;
    }
    this.revealEarly(win);
    const panel = win.PopupNotifications.panel;
    try {
      this.m.conceal.makeNonnative(panel);
      this.m.conceal.quietAnchor(panel);
      const holder = { session: null };
      const entry = { handle: this.concealFor(win, holder), holder, timer: null };
      this.early.set(win, entry);
      // P64 (c): a hiding nobody adopts or ends never outlives this, even
      // when the panel's popupshown, and so onPrompt, never comes.
      entry.timer = win.setTimeout(() => {
        if (this.early.get(win) === entry) {
          this.revealEarly(win);
          this.problem("hide-timeout");
        }
      }, EARLY_HIDE_MS);
    } catch {
      // onPrompt tries again, and records conceal-failed if it fails too.
      // The panel is a plain window by now, so its record of `nonnative`
      // stays: P64 (a) must not take it for a native one. Its sweep, or
      // popuphidden, takes the record off. P67: the anchor is not quiet for
      // a prompt that may show, so panel.js acts on it as in stock Zen.
      this.m.conceal.releaseAnchor(win);
    }
  }

  // Hides the panel with P44 and P47's guards, on behalf of holder.session
  // once there is one; until then Esc does nothing and focus goes to the
  // page.
  concealFor(win, holder) {
    return this.m.conceal.concealPanel(win, {
      escape: e => {
        if (holder.session) {
          this.onEscape(holder.session, e);
        }
      },
      focusTarget: () =>
        holder.session ? this.focusTarget(holder.session) : win.gBrowser.selectedBrowser,
    });
  }

  // Shows the panel again if a hiding taken in popupshowing is still unowned.
  revealEarly(win) {
    const early = this.early.get(win);
    if (!early) {
      return;
    }
    this.early.delete(win);
    try {
      win.clearTimeout(early.timer);
    } catch {
      // The window is gone, and its timers with it.
    }
    try {
      early.handle.restore();
    } catch (e) {
      logError(`reveal failed: ${e?.name ?? "error"}`);
    }
  }

  onPrompt(win) {
    try {
      this.openFor(win);
    } finally {
      this.revealEarly(win);
    }
  }

  openFor(win) {
    if (this.stopped || this.state !== "active" || this.sessions.has(win)) {
      return;
    }
    const m = this.m;
    let info;
    let model;
    let captures;
    const tabs = new Set();
    const browsers = new Map();
    try {
      const shown = win.document.getElementById(m.prompt.IDS.element)?.notification;
      if (shown && (this.declined.has(shown) || this.sharing.has(shown))) {
        return;
      }
      const read = m.prompt.readPrompt(win);
      if (!read.ok) {
        if (!SILENT.has(read.reason)) {
          this.problem(read.reason);
        }
        return;
      }
      info = read.info;
      const n = info.notification;
      if (this.declined.has(n) || this.sharing.has(n)) {
        return;
      }
      info = { ...info, osEntry: this.osEntryOf(info, true) };
      captures = this.capturesOf(info, true);
      if (!this.offersRows(info, captures)) {
        // Nothing to offer: not a problem (SILENT).
        return;
      }
      // The port selects a screen or window only among these rows.
      info.captures = captures.rows;
      const facts = m.tabs.tabFacts(info.entries, win, info.browser, Services);
      if (!facts.ok) {
        this.problem(facts.reason);
        return;
      }
      // P64 (a): a panel that opened before the add-on could make it a
      // plain window (no record of `nonnative`, P48) may be a native
      // popover, which no style hides. Zen's prompt stays as it is.
      if (!win.PopupNotifications.panel.hasAttribute(m.conceal.NATIVE_MARK)) {
        this.record("prompt shown-native");
        return;
      }
      model = m.rows.buildModel(
        facts.facts,
        m.tabs.hereOf(win),
        m.tabs.spaceNamesOf(win),
        { available: !!info.osEntry, macos: Services.appinfo.OS === "Darwin" },
        captures.rows
      );
      // Tab entries only: a window's id can equal a tab's browserId.
      const ids = new Set(
        info.entries.filter(e => e.mediaSource === "browser").map(e => e.deviceId)
      );
      for (const w of Services.wm.getEnumerator("navigator:browser")) {
        for (const t of tabsOf(w)) {
          const id = t.linkedPanel && t.linkedBrowser ? String(t.linkedBrowser.browserId) : null;
          if (id !== null && ids.has(id)) {
            tabs.add(t);
            browsers.set(id, t.linkedBrowser);
          }
        }
      }
    } catch {
      this.problem("internal");
      return;
    }

    // P33: the delay is read once per picker; the overlay and onEffect both
    // use it, each with its own open and activate times.
    const delayMs = this.enableDelay();
    const session = {
      win,
      info,
      tabs,
      picker: null,
      conceal: null,
      done: false,
      times: { openedAt: ChromeUtils.now(), activatedAt: null, delayMs },
    };
    try {
      const tabRows = model.others.reduce((n, g) => n + g.rows.length, model.here.length);
      const screens = captures.rows.filter(r => r.kind === "screen").length;
      // Counts only: never a window's title.
      this.record(
        `prompt ${info.entries.length} entries, ${tabRows} tabs, ${model.here.length} here, ` +
          `${screens} screens, ${captures.rows.length - screens} windows, ` +
          `${captures.hidden} hidden`
      );
      // P12: another space's hosts only once Tab revealed them.
      this.recordHosts(model.here);
      session.picker = m.overlay.openPicker(win, model, {
        onEffect: effect => this.onEffect(session, effect),
        onReveal: () => {
          if (!session.done && !this.stopped) {
            this.recordHosts(model.others.flatMap(g => g.rows));
          }
        },
        browserFor: id => browsers.get(id) ?? null,
        previewMode: m.config.PREVIEW_MODE,
        cssUrl: `resource://${this.host}/${CSS}`,
        PageThumbs: this.internal("PageThumbs"),
        site: info.site,
        now: () => ChromeUtils.now(),
        delayMs,
        livePreview: this.livePreview(),
        accel: Services.appinfo.OS === "Darwin" ? "meta" : "ctrl",
      });
    } catch (e) {
      const code = e?.message;
      this.problem(code === "no-mount" || code === "already-open" ? code : "internal");
      return;
    }
    // P35: hide Zen's panel only once the picker is open, and only when
    // the panel shows the share prompt alone; P48: or keep the hiding taken
    // as it showed. If that fails, no picker.
    try {
      if (m.conceal.showsOnly(win.PopupNotifications.panel, m.prompt.IDS.element)) {
        const early = this.early.get(win);
        if (early) {
          this.early.delete(win);
          win.clearTimeout(early.timer);
          early.holder.session = session;
          session.conceal = early.handle;
        } else {
          session.conceal = this.concealFor(win, { session });
        }
      }
    } catch {
      session.done = true;
      this.closePicker(session);
      m.conceal.revealPanel(win);
      this.problem("conceal-failed");
      return;
    }
    this.sessions.set(win, session);
  }

  // P44: while the session hides the panel, every Escape in its window comes
  // here. The open picker takes it as its own Esc (a decline); during the
  // Allow wait or a decline it does nothing.
  onEscape(session, e) {
    if (!session.done && !this.stopped && this.sessions.get(session.win) === session) {
      session.picker?.escape(e);
    }
  }

  // P44: where focus goes when it enters the hidden panel: the picker's
  // search box while it is open, otherwise the page.
  focusTarget(session) {
    const { picker } = session;
    if (!session.done && picker?.isOpen()) {
      return picker.search;
    }
    return session.win.gBrowser.selectedBrowser;
  }

  // P51: the picker previews a window or screen live only where Zen's own
  // prompt would: its previews pref on, and on macOS, screen capture not
  // denied. The OS state is only read, never requested. False when unreadable.
  livePreview() {
    try {
      if (!Services.prefs.getBoolPref(PREVIEWS_PREF, true)) {
        return false;
      }
      if (Services.appinfo.OS === "Darwin") {
        const os = Cc["@mozilla.org/ospermissionrequest;1"].getService(
          Ci.nsIOSPermissionRequest
        );
        const state = {};
        os.getScreenCapturePermissionState(state);
        return state.value !== os.PERMISSION_STATE_DENIED;
      }
      return true;
    } catch {
      return false;
    }
  }

  // security.notification_enable_delay, or the default when unreadable.
  enableDelay() {
    const fallback = this.m.config.TIMING.defaultDelayMs;
    try {
      return this.m.arming.delayOf(Services.prefs.getIntPref(DELAY_PREF, fallback), fallback);
    } catch {
      return fallback;
    }
  }

  onEffect(session, effect) {
    if (session.done || this.stopped) {
      return;
    }
    // P33, defense in depth: the overlay gates commits too.
    if (
      (effect.type === "share" || effect.type === "os") &&
      !this.m.arming.isArmed(session.times, ChromeUtils.now())
    ) {
      this.record("share refused: not armed");
      return;
    }
    if (effect.type === "cancel") {
      // P36: Esc and Cancel decline. Not a commit, so arming does not
      // gate it; the overlay already ignored a held or untrusted one.
      this.decline(session);
    } else if (effect.type === "share") {
      // The port checks the kind against the entry (P19).
      this.share(session, { kind: effect.kind, deviceId: effect.deviceId });
    } else if (effect.type === "os") {
      // P52: the OS row exists only with an OS entry.
      const os = session.info.osEntry;
      if (os) {
        this.share(session, { kind: "os", deviceId: os.deviceId });
      }
    }
  }

  outcome(outcome, deviceId) {
    this.lastOutcome = outcome;
    this.record(`share ${outcome} device ${deviceId ?? "-"}`);
  }

  // Runs the one share for this prompt. Nothing runs it again (P18).
  share(session, target) {
    session.done = true;
    const { win, info } = session;
    this.sharing.add(info.notification);
    const m = this.m;
    let port;
    try {
      const stock = m.prompt.makePort(win, info, {
        Services,
        ChromeUtils,
        webrtcUI: this.internal("webrtcUI"),
      });
      // After shutdown or setEnabled(false) the prompt is never current,
      // so no click follows. P43: once it is not current (gone after the
      // Allow click, replaced or hidden), the panel shows again, before
      // the stream check.
      const generation = this.generation;
      port = {
        ...stock,
        isCurrent: () => {
          const current =
            !this.stopped && this.generation === generation && stock.isCurrent();
          if (!current) {
            this.reveal(session);
          }
          return current;
        },
      };
    } catch {
      this.closeSession(session);
      this.problem("internal");
      this.outcome("aborted", target.deviceId);
      return;
    }
    const clock = {
      now: () => ChromeUtils.now(),
      sleep: ms => new Promise(resolve => win.setTimeout(resolve, ms)),
    };
    this.running.add(session);
    m.share
      .runShare({
        port,
        clock,
        mode: m.config.SHARE_MODE,
        target,
        // The panel stays hidden through the Allow wait (P35).
        closePicker: () => this.closePicker(session),
        stopPreview: () => session.picker.stopPreview(),
        timing: m.config.TIMING,
        // runShare logs step codes only ("share: click 1").
        log: line => this.record(String(line)),
      })
      .then(
        outcome => this.outcome(outcome, target.deviceId),
        () => this.outcome("aborted", target.deviceId)
      )
      .finally(() => {
        this.running.delete(session);
        this.reveal(session);
      });
  }

  // Declines the session's prompt once (P36, P38): abandons its own
  // notification, so Zen denies the request and sets no permission. When
  // that fails, Zen's prompt shows again and the user decides there. The
  // panel shows again right after the first check that the notification
  // went, and at the latest when the sequence settles.
  decline(session) {
    session.done = true;
    const { win, info } = session;
    this.declined.add(info.notification);
    // The overlay already closed itself; this forgets the session.
    this.closePicker(session);
    const m = this.m;
    let port;
    try {
      const stock = m.prompt.makePort(win, info, {
        Services,
        ChromeUtils,
        webrtcUI: this.internal("webrtcUI"),
      });
      const generation = this.generation;
      port = {
        isCurrent: () => !this.stopped && this.generation === generation && stock.isCurrent(),
        abandon: () => stock.abandon(),
        isGone: () => stock.isGone(),
      };
    } catch {
      this.reveal(session);
      this.problem("decline-failed");
      this.outcome("cancelled", null);
      return;
    }
    const clock = {
      now: () => ChromeUtils.now(),
      sleep: ms => new Promise(resolve => win.setTimeout(resolve, ms)),
    };
    m.decline
      .runDecline({
        port,
        clock,
        timing: m.config.TIMING,
        // runDecline logs step codes only ("decline: abandon").
        log: line => this.record(String(line)),
        reveal: () => this.reveal(session),
      })
      .then(
        result => {
          if (result === "declined") {
            this.outcome("declined", null);
            return;
          }
          if (result !== "kept") {
            this.problem("decline-failed");
          }
          this.outcome("cancelled", null);
        },
        () => {
          this.problem("decline-failed");
          this.outcome("cancelled", null);
        }
      )
      .finally(() => this.reveal(session));
  }

  forget(session) {
    if (this.sessions.get(session.win) === session) {
      this.sessions.delete(session.win);
    }
  }

  // Closes the picker; Zen's panel stays as it is.
  closePicker(session) {
    this.forget(session);
    try {
      session.picker?.close();
    } catch (e) {
      logError(`close failed: ${e?.name ?? "error"}`);
    }
  }

  // Shows Zen's panel again, if this session hid it.
  reveal(session) {
    try {
      session.conceal?.restore();
    } catch (e) {
      logError(`reveal failed: ${e?.name ?? "error"}`);
    }
    session.conceal = null;
  }

  // Shows the panel first, so the picker hands focus back to Zen's prompt
  // as it was before the picker opened.
  closeSession(session) {
    this.reveal(session);
    this.closePicker(session);
  }

  // Closes the window's picker without sharing.
  closeIn(win) {
    const session = this.sessions.get(win);
    if (session) {
      session.done = true;
      this.closeSession(session);
    }
  }

  // Closes every picker that lists `tab`, without sharing.
  closeListing(tab) {
    for (const session of [...this.sessions.values()]) {
      if (session.tabs.has(tab)) {
        session.done = true;
        this.closeSession(session);
      }
    }
  }

  async status() {
    await this.start();
    return statusOf({
      version: this.version,
      state: this.stopped ? "disabled" : this.state,
      failedChecks: this.failedChecks,
      promptProblems: this.promptProblems,
      shareMode: this.m?.config.SHARE_MODE ?? "",
      previewMode: this.m?.config.PREVIEW_MODE ?? "",
      lastOutcome: this.lastOutcome,
      debug: this.debug,
    });
  }

  // Off empties the log: it holds hosts.
  setDebug(on) {
    this.debug = !!on;
    if (!this.debug) {
      this.log.length = 0;
    }
  }

  // Off closes every picker and stops listening; on runs the startup checks
  // again, also after they failed. A failed module load cannot be retried.
  setEnabled(on) {
    const run = this.toggling.then(() => this.toggle(!!on));
    this.toggling = run.catch(() => {});
    return run;
  }

  async toggle(on) {
    await this.start();
    if (this.stopped || !this.m) {
      return this.status();
    }
    if (!on) {
      if (this.state !== "disabled") {
        this.generation++;
        this.stopWatching();
        this.state = "disabled";
        this.record("disabled");
      }
    } else if (this.state !== "active") {
      this.stopWatching();
      this.failedChecks = [];
      this.state = "starting";
      this.record("enabled");
      await this.watch();
    }
    return this.status();
  }

  shutdown() {
    this.stopped = true;
    this.state = "disabled";
    this.generation++;
    this.stopWatching();
    this.firstWindow?.();
    this.m = null;
    resProto.setSubstitution(this.host, null);
  }
}

this.sharePicker = class extends ExtensionAPI {
  // Null once shut down: an API call after onShutdown must not start a new
  // Picker, which would register the resource host again.
  get picker() {
    if (this.closed) {
      return null;
    }
    this._picker ??= new Picker(this.extension.rootURI, this.extension.version);
    return this._picker;
  }

  onShutdown() {
    this.closed = true;
    this._picker?.shutdown();
    this._picker = null;
  }

  getAPI() {
    const version = this.extension.version;
    const closed = async () => statusOf({ version, state: "disabled" });
    return {
      sharePicker: {
        start: () => this.picker?.status() ?? closed(),
        getStatus: () => this.picker?.status() ?? closed(),
        setEnabled: on => this.picker?.setEnabled(on) ?? closed(),
        setDebug: async on => {
          this.picker?.setDebug(on);
        },
        getLog: async () => [...(this.picker?.log ?? [])],
      },
    };
  }
};
