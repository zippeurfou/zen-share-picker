// Maps the stock prompt's tab entries to tabs, and reads where the
// requesting window is. Each function catches its own throws.

const NO_HERE = Object.freeze({ spaceId: null, ucid: null });

// Every tab of a window, in every space: gBrowser.tabs holds only the active
// space's tabs in Zen.
function tabsOf(w) {
  const tabs = new Set(w.gBrowser?.tabs ?? []);
  for (const t of w.gZenWorkspaces?.allStoredTabs ?? []) {
    tabs.add(t);
  }
  return tabs;
}

function hostOf(uri) {
  try {
    return uri?.host ?? "";
  } catch {
    // about: and other URIs without a host throw.
    return "";
  }
}

// `w` is the window the tab was found in.
function spaceOf(tab, w) {
  if (w.gZenWorkspaces?.privateWindowOrDisabled !== false) {
    return null;
  }
  const id = tab.getAttribute("zen-workspace-id");
  return id ? id : null;
}

function factOf(entry, { tab, w }, promptWin, requestingBrowser) {
  const browser = tab.linkedBrowser;
  const browserId = String(browser.browserId);
  const uri = browser.currentURI;
  return {
    deviceId: entry.deviceId,
    syncKey: tab.id || "browser:" + browserId,
    inPromptWindow: w === promptWin,
    contentsVisible: tab._zenContentsVisible === true,
    lastAccessed: typeof tab.lastAccessed === "number" ? tab.lastAccessed : 0,
    title: tab.label ?? "",
    host: hostOf(uri),
    icon: uri?.spec ? "page-icon:" + uri.spec : "",
    spaceId: spaceOf(tab, w),
    essential: tab.hasAttribute("zen-essential"),
    ucid: typeof tab.userContextId === "number" ? tab.userContextId : null,
    requesting: browser === requestingBrowser,
  };
}

export function tabFacts(entries, promptWin, requestingBrowser, Services) {
  try {
    const byId = new Map();
    for (const w of Services.wm.getEnumerator("navigator:browser")) {
      for (const tab of tabsOf(w)) {
        if (tab.linkedPanel && tab.linkedBrowser) {
          byId.set(String(tab.linkedBrowser.browserId), { tab, w });
        }
      }
    }
    const facts = [];
    for (const entry of entries) {
      if (entry.mediaSource !== "browser") {
        continue;
      }
      const found = byId.get(entry.deviceId);
      if (!found) {
        return { ok: false, reason: "unmapped-entry" };
      }
      facts.push(factOf(entry, found, promptWin, requestingBrowser));
    }
    return { ok: true, facts };
  } catch {
    return { ok: false, reason: "tab-error" };
  }
}

export function hereOf(win) {
  try {
    const zw = win.gZenWorkspaces;
    if (zw.privateWindowOrDisabled !== false) {
      return { ...NO_HERE };
    }
    const space = zw.getActiveWorkspaceFromCache();
    const ucid = zw.getCurrentSpaceContainerId();
    if (typeof space?.uuid !== "string" || !space.uuid || typeof ucid !== "number") {
      return { ...NO_HERE };
    }
    return { spaceId: space.uuid, ucid };
  } catch {
    return { ...NO_HERE };
  }
}

export function spaceNamesOf(win) {
  try {
    const names = new Map();
    for (const s of win.gZenWorkspaces.getWorkspaces()) {
      if (typeof s?.uuid === "string") {
        names.set(s.uuid, typeof s.name === "string" ? s.name : "");
      }
    }
    return names;
  } catch {
    return new Map();
  }
}
