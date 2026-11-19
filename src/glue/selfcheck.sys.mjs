// The startup checks: the Zen and Firefox parts the add-on relies on. If any
// fails, the add-on stays inert and the stock prompt is left as it is.
//
// startupChecks(win, { ChromeUtils, previewMode }) -> the failed codes, in
// CHECKS order; empty when all pass. A check that throws fails. Never throws.

import { IDS } from "./prompt.sys.mjs";

export const CHECKS = Object.freeze([
  // win.PopupNotifications.panel is #notification-popup (browser.js).
  "popup-notifications",
  // The share prompt's elements (browser.xhtml, webRTC-shareDevices).
  "prompt-elements",
  // webrtcUI.getActiveStreams, to verify a share.
  "webrtc-ui",
  // The Zen space API tabs.sys.mjs reads, and the space-switch listeners
  // api.js adds.
  "zen-spaces",
  // PageThumbs.captureTabPreviewThumbnail, for the snapshot preview.
  "page-thumbs",
]);

const PROMPT_ELEMENTS = [IDS.element, IDS.screenSection, IDS.menulist, IDS.menupopup];
const isFn = f => typeof f === "function";

const TESTS = {
  "popup-notifications": win => {
    const panel = win.PopupNotifications.panel;
    return !!panel && panel === win.document.getElementById("notification-popup");
  },
  "prompt-elements": win =>
    PROMPT_ELEMENTS.every(id => !!win.document.getElementById(id)),
  "webrtc-ui": (win, { ChromeUtils }) =>
    isFn(
      ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs").webrtcUI
        .getActiveStreams
    ),
  "zen-spaces": win => {
    const zw = win.gZenWorkspaces;
    return (
      isFn(zw.getActiveWorkspaceFromCache) &&
      isFn(zw.getCurrentSpaceContainerId) &&
      isFn(zw.getWorkspaces) &&
      isFn(zw.addChangeListeners) &&
      isFn(zw.removeChangeListeners) &&
      typeof zw.privateWindowOrDisabled === "boolean"
    );
  },
  "page-thumbs": (win, { ChromeUtils, previewMode }) =>
    previewMode !== "snapshot" ||
    isFn(
      ChromeUtils.importESModule("resource://gre/modules/PageThumbs.sys.mjs")
        .PageThumbs.captureTabPreviewThumbnail
    ),
};

export function startupChecks(win, { ChromeUtils, previewMode } = {}) {
  const failed = [];
  for (const code of CHECKS) {
    let ok = false;
    try {
      ok = TESTS[code](win, { ChromeUtils, previewMode }) === true;
    } catch {
      ok = false;
    }
    if (!ok) {
      failed.push(code);
    }
  }
  return failed;
}
