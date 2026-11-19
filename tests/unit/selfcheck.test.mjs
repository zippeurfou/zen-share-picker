import test from "node:test";
import assert from "node:assert/strict";
import { CHECKS, startupChecks } from "../../src/glue/selfcheck.sys.mjs";

const PROMPT_IDS = [
  "webRTC-shareDevices-notification",
  "webRTC-selectWindowOrScreen",
  "webRTC-selectWindow-menulist",
  "webRTC-selectWindow-menupopup",
];

// A browser window and ChromeUtils made of plain objects, with every part
// startupChecks reads. `over` edits them before the check runs.
function setup(over = () => {}) {
  const fn = () => {};
  const panel = { id: "notification-popup" };
  const elements = new Map([["notification-popup", panel]]);
  for (const id of PROMPT_IDS) {
    elements.set(id, { id });
  }
  const win = {
    document: { getElementById: id => elements.get(id) ?? null },
    PopupNotifications: { panel },
    gZenWorkspaces: {
      getActiveWorkspaceFromCache: fn,
      getCurrentSpaceContainerId: fn,
      getWorkspaces: fn,
      addChangeListeners: fn,
      removeChangeListeners: fn,
      privateWindowOrDisabled: false,
    },
  };
  const modules = {
    "resource:///modules/webrtcUI.sys.mjs": { webrtcUI: { getActiveStreams: fn } },
    "resource://gre/modules/PageThumbs.sys.mjs": {
      PageThumbs: { captureTabPreviewThumbnail: fn },
    },
  };
  const ChromeUtils = {
    importESModule(url) {
      if (!(url in modules)) {
        throw new Error("no module " + url);
      }
      return modules[url];
    },
  };
  const parts = { win, elements, modules, ChromeUtils, panel };
  over(parts);
  return parts;
}

const run = (parts, previewMode = "snapshot") =>
  startupChecks(parts.win, { ChromeUtils: parts.ChromeUtils, previewMode });

const throwing = () => {
  throw new Error("boom");
};

test("a_complete_window_passes", () => {
  assert.deepEqual(run(setup()), []);
  assert.deepEqual(CHECKS, [
    "popup-notifications",
    "prompt-elements",
    "webrtc-ui",
    "zen-spaces",
    "page-thumbs",
  ]);
});

const CASES = {
  "popup-notifications": [
    p => delete p.win.PopupNotifications,
    p => (p.win.PopupNotifications = { panel: null }),
    p => (p.win.PopupNotifications = { panel: { id: "notification-popup" } }),
    p => p.elements.delete("notification-popup"),
    p => Object.defineProperty(p.win.PopupNotifications, "panel", { get: throwing }),
  ],
  "prompt-elements": [
    ...PROMPT_IDS.map(id => p => p.elements.delete(id)),
    p => {
      const el = p.elements.get(PROMPT_IDS[2]);
      p.elements.delete(PROMPT_IDS[2]);
      p.elements.set("webRTC-selectWindow-menulist-renamed", el);
    },
    p => {
      const get = p.win.document.getElementById;
      p.win.document.getElementById = id => (id === PROMPT_IDS[3] ? throwing() : get(id));
    },
  ],
  "webrtc-ui": [
    p => delete p.modules["resource:///modules/webrtcUI.sys.mjs"],
    p => (p.modules["resource:///modules/webrtcUI.sys.mjs"] = { webrtcUI: {} }),
    p =>
      (p.modules["resource:///modules/webrtcUI.sys.mjs"] = {
        webrtcUI: { getActiveStreamsRenamed() {} },
      }),
    p =>
      Object.defineProperty(
        p.modules["resource:///modules/webrtcUI.sys.mjs"].webrtcUI,
        "getActiveStreams",
        { get: throwing }
      ),
  ],
  "zen-spaces": [
    p => delete p.win.gZenWorkspaces,
    p => delete p.win.gZenWorkspaces.getActiveWorkspaceFromCache,
    p => delete p.win.gZenWorkspaces.getCurrentSpaceContainerId,
    p => (p.win.gZenWorkspaces.getWorkspaces = undefined),
    p => {
      p.win.gZenWorkspaces.getAllWorkspaces = p.win.gZenWorkspaces.getWorkspaces;
      delete p.win.gZenWorkspaces.getWorkspaces;
    },
    // The space-switch listeners.
    p => delete p.win.gZenWorkspaces.addChangeListeners,
    p => (p.win.gZenWorkspaces.removeChangeListeners = undefined),
    p => delete p.win.gZenWorkspaces.privateWindowOrDisabled,
    p => (p.win.gZenWorkspaces.privateWindowOrDisabled = "false"),
    p =>
      Object.defineProperty(p.win.gZenWorkspaces, "privateWindowOrDisabled", {
        get: throwing,
      }),
    p => Object.defineProperty(p.win, "gZenWorkspaces", { get: throwing }),
  ],
  "page-thumbs": [
    p => delete p.modules["resource://gre/modules/PageThumbs.sys.mjs"],
    p => (p.modules["resource://gre/modules/PageThumbs.sys.mjs"] = { PageThumbs: {} }),
    p =>
      Object.defineProperty(
        p.modules["resource://gre/modules/PageThumbs.sys.mjs"].PageThumbs,
        "captureTabPreviewThumbnail",
        { get: throwing }
      ),
  ],
};

for (const [code, edits] of Object.entries(CASES)) {
  test(`${code}_fails_when_its_part_is_missing_renamed_or_throws`, () => {
    edits.forEach((edit, i) => {
      assert.deepEqual(run(setup(edit)), [code], `${code} case ${i}`);
    });
  });
}

test("page_thumbs_is_not_checked_without_snapshots", () => {
  const parts = setup(p => delete p.modules["resource://gre/modules/PageThumbs.sys.mjs"]);
  assert.deepEqual(run(parts, "none"), []);
  assert.deepEqual(run(parts, "snapshot"), ["page-thumbs"]);
});

test("every_failure_is_listed_in_order_and_nothing_throws", () => {
  const parts = setup(p => {
    p.win.document.getElementById = throwing;
    p.ChromeUtils.importESModule = throwing;
    Object.defineProperty(p.win, "gZenWorkspaces", { get: throwing });
    Object.defineProperty(p.win, "PopupNotifications", { get: throwing });
  });
  assert.deepEqual(run(parts), CHECKS);
  assert.deepEqual(startupChecks(null, { ChromeUtils: null, previewMode: "snapshot" }), CHECKS);
});
