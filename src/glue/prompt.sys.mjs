// Reads Zen's stock screen-share prompt and drives it for runShare and
// runDecline.
//
// Nothing here calls mainAction.callback, _onButtonEvent or webrtc:Allow.
// The only way this module acts on the prompt is through the PromptPort:
// select() picks a dropdown item the way a user's pick does, and
// clickAllow() clicks the real Allow button, which keeps every check of
// PopupNotifications._onButtonEvent. The only other way is abandon() (P38):
// PopupNotifications.remove(notification, true) on the session's own
// notification, which Zen treats as a request abandoned without a user
// response: WebRTC denies it and sets no permission. Each function catches
// its own throws, except abandon(), whose throw runDecline handles.

import { TIMING } from "../lib/config.mjs";

export const IDS = Object.freeze({
  notification: "webRTC-shareDevices",
  element: "webRTC-shareDevices-notification",
  screenSection: "webRTC-selectWindowOrScreen",
  menulist: "webRTC-selectWindow-menulist",
  menupopup: "webRTC-selectWindow-menupopup",
});

const fail = reason => ({ ok: false, reason });

// P34: a screen request that also asks for audio input. A microphone shows
// its own section; audio capture shows only in the prompt's message
// (WebRTCParent.sys.mjs prompt and getPromptMessageId).
const MIC_SECTION = "webRTC-selectMicrophone";
const L10N = ["browser/webrtcIndicator.ftl", "branding/brand.ftl"];
const AUDIO_CAPTURE = [
  ["webrtc-allow-share-screen-and-audio-capture", { origin: "<>", thirdParty: "{}" }],
  [
    "webrtc-allow-share-screen-and-audio-capture-unsafe-delegation",
    { origin: "<>", thirdParty: "{}" },
  ],
  ["webrtc-allow-share-screen-and-audio-capture-with-file", undefined],
];

function asksForAudio(win, mic, notification) {
  if (!mic.hidden) {
    return true;
  }
  const l10n = new win.Localization(L10N, true);
  return AUDIO_CAPTURE.some(
    ([id, args]) => l10n.formatValueSync(id, args) === notification.message
  );
}

// The "Select a window or screen" item: value "-1", no device
// (WebRTCParent.sys.mjs listScreenShareDevices).
function isPlaceholder(item) {
  return (
    item.localName === "menuitem" &&
    item.getAttribute("value") === "-1" &&
    item.deviceId === undefined
  );
}

function read(win, showing) {
  const doc = win.document;
  const element = doc.getElementById(IDS.element);
  const notification = element?.notification;
  if (!notification || notification.id !== IDS.notification) {
    return fail("no-notification");
  }
  const browser = notification.browser;
  const PN = win.PopupNotifications;
  if (
    !browser ||
    PN.getNotification(IDS.notification, browser) !== notification ||
    !(PN.panel.state === "open" || (showing && PN.panel.state === "showing"))
  ) {
    return fail("no-notification");
  }
  const section = doc.getElementById(IDS.screenSection);
  if (!section || section.hidden) {
    return fail("not-screen-request");
  }
  const mic = doc.getElementById(MIC_SECTION);
  if (!mic) {
    return fail("no-mic-section");
  }
  if (asksForAudio(win, mic, notification)) {
    return fail("mixed-request");
  }
  const menulist = doc.getElementById(IDS.menulist);
  const menupopup = doc.getElementById(IDS.menupopup);
  if (!menulist || !menupopup || menupopup.parentNode !== menulist) {
    return fail("no-menulist");
  }
  if (!element.button) {
    return fail("no-allow-button");
  }

  const entries = [];
  const seen = new Set();
  for (const item of menupopup.children) {
    if (item.localName === "menuseparator" || isPlaceholder(item)) {
      continue;
    }
    if (
      item.localName !== "menuitem" ||
      item.deviceId === undefined ||
      item.deviceId === null ||
      typeof item.mediaSource !== "string" ||
      item.mediaSource === ""
    ) {
      return fail("bad-entry");
    }
    const deviceId = String(item.deviceId);
    // A tab's browserId may equal a screen's or a window's id: only the
    // same id twice for one kind is wrong.
    const key = JSON.stringify([item.mediaSource, deviceId]);
    if (seen.has(key)) {
      return fail("bad-entry");
    }
    seen.add(key);
    entries.push({ deviceId, mediaSource: item.mediaSource, item });
  }
  if (!entries.some(e => e.mediaSource === "browser")) {
    return fail("no-tab-entries");
  }

  const initialItem = menulist.selectedItem ?? null;
  // Zen pre-selects only the OS-picker item (canRequestOsLevelPrompt); any
  // other entry is never treated as the OS row.
  const preselected = entries.find(e => e.item === initialItem);
  const osEntry =
    preselected && preselected.mediaSource !== "browser" ? preselected : null;

  // P37: the asking site, for the picker's header. Zen sets no name for a
  // local file (WebRTCParent.sys.mjs prompt), and a secondName only for a
  // request delegated to a third party.
  const options = notification.options ?? {};
  const named = v => (typeof v === "string" && v !== "" ? v : null);
  const site = { name: named(options.name), secondName: named(options.secondName) };

  return {
    ok: true,
    info: { notification, element, browser, entries, osEntry, initialItem, site },
  };
}

// `showing` also reads a panel that is about to show (P48: popupshowing).
export function readPrompt(win, { showing = false } = {}) {
  try {
    return read(win, showing);
  } catch {
    return fail("read-error");
  }
}

function guard(fn, fallback) {
  return (...args) => {
    try {
      return fn(...args);
    } catch {
      return fallback;
    }
  };
}

export function makePort(win, info, { Services, ChromeUtils, webrtcUI }) {
  const doc = win.document;
  const menulist = () => doc.getElementById(IDS.menulist);
  const { element, notification, browser } = info;

  return {
    isCurrent: guard(
      () =>
        element.notification === notification &&
        win.PopupNotifications.getNotification(IDS.notification, browser) ===
          notification &&
        win.PopupNotifications.panel.state === "open",
      false
    ),

    selectedDeviceId: guard(() => {
      const item = menulist().selectedItem;
      return item?.deviceId === undefined || item.deviceId === null
        ? null
        : String(item.deviceId);
    }, null),

    // As a user's pick: select the item, then its command event runs Zen's
    // own checks (invalidselection) and starts the stock preview. A "tab"
    // target must be a tab entry, and an "os" target the recorded OS entry.
    select: guard((deviceId, kind) => {
      const list = menulist();
      // Found by kind and id: another kind may use the same id.
      let entry = null;
      if (kind === "tab") {
        entry =
          info.entries.find(e => e.deviceId === deviceId && e.mediaSource === "browser") ??
          null;
      } else if (kind === "os" && info.osEntry && info.osEntry.deviceId === deviceId) {
        entry = info.osEntry;
      }
      if (!entry || entry.item.parentNode?.parentNode !== list) {
        return false;
      }
      list.selectedItem = entry.item;
      entry.item.doCommand();
      return true;
    }, false),

    // Puts the first selection back without a command event, and marks
    // the selection invalid again when it is, as Zen's own check would.
    restore: guard(() => {
      const list = menulist();
      list.selectedItem = info.initialItem;
      const item = list.selectedItem;
      if (!item || item.hasAttribute("disabled")) {
        element.setAttribute("invalidselection", "true");
      }
    }, undefined),

    allowEnabled: guard(() => {
      const button = element.button;
      return (
        !!button &&
        !button.disabled &&
        !element.hasAttribute("invalidselection") &&
        !element.hasAttribute("mainactiondisabled")
      );
    }, false),

    windowActive: guard(
      () =>
        Services.focus.activeWindow === win &&
        !element.matches(":-moz-window-inactive"),
      false
    ),

    // NaN when unreadable: runShare then never clicks.
    msSinceShown: guard(() => {
      const shown = notification.timeShown;
      return typeof shown === "number" ? ChromeUtils.now() - shown : NaN;
    }, NaN),

    delayMs: guard(
      () =>
        Services.prefs.getIntPref(
          "security.notification_enable_delay",
          TIMING.defaultDelayMs
        ),
      TIMING.defaultDelayMs
    ),

    clickAllow: guard(() => {
      element.button.click();
    }, undefined),

    // P38: abandons the request, as Zen does for a prompt removed without
    // a user response (PopupNotifications.sys.mjs remove, WebRTCParent.sys.mjs
    // "removed" with withoutUserResponse: denyRequest). Not guarded.
    abandon() {
      win.PopupNotifications.remove(notification, true);
    },

    // Whether the browser's share notification is no longer this one.
    isGone: guard(
      () => win.PopupNotifications.getNotification(IDS.notification, browser) !== notification,
      false
    ),

    sharingShows: guard(
      deviceId =>
        webrtcUI
          .getActiveStreams(true, true, true, true, true)
          .some(
            s =>
              s.browser === browser &&
              (s.devices ?? []).some(
                d => d.mediaSource === "browser" && String(d.rawId) === deviceId
              )
          ),
      false
    ),
  };
}
