import { visibleRows } from "../lib/state.mjs";

// The picker's preview of the highlighted row. Both loops capture only the
// target they are given, and stop() ends them for good: a stopped loop
// ignores every later setTarget.

// Still snapshots, the way Firefox's tab hover preview takes them, drawn into
// `canvas`. One capture at a time; a capture for a target that is no longer
// current is dropped. While the target stays the same, it is captured again
// every `intervalMs`. onPaint(browser) runs after `canvas` shows `browser`,
// onClear() after `canvas` was emptied.
export function startSnapshots(
  win,
  { canvas, PageThumbs, intervalMs, onPaint = () => {}, onClear = () => {} }
) {
  let target = null;
  let gen = 0;
  let timer = null;
  let inFlight = false;
  let again = false;
  let stopped = false;

  function clear() {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    onClear();
  }

  function cancelTimer() {
    if (timer !== null) {
      win.clearTimeout(timer);
      timer = null;
    }
  }

  function kick() {
    cancelTimer();
    if (stopped || target === null) {
      return;
    }
    if (inFlight) {
      again = true;
      return;
    }
    capture();
  }

  async function capture() {
    inFlight = true;
    const mine = gen;
    const browser = target;
    const scratch = win.document.createElementNS(
      "http://www.w3.org/1999/xhtml",
      "canvas"
    );
    scratch.width = canvas.width;
    scratch.height = canvas.height;
    let ok = false;
    try {
      ok = await PageThumbs.captureTabPreviewThumbnail(browser, scratch);
    } catch {
      ok = false;
    }
    inFlight = false;
    if (stopped) {
      return;
    }
    if (ok && mine === gen) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(scratch, 0, 0);
      onPaint(browser);
    }
    if (again) {
      again = false;
      kick();
      return;
    }
    if (mine === gen && target !== null) {
      timer = win.setTimeout(() => {
        timer = null;
        kick();
      }, intervalMs);
    }
  }

  return {
    setTarget(browser) {
      if (stopped || browser === target) {
        return;
      }
      gen++;
      target = browser ?? null;
      cancelTimer();
      clear();
      kick();
    },
    stop() {
      if (stopped) {
        return;
      }
      stopped = true;
      gen++;
      target = null;
      again = false;
      cancelTimer();
      clear();
    },
  };
}

// A live capture through Firefox's own <webrtc-preview>, as the stock prompt
// shows its selected entry. A target is {deviceId, mediaSource}, where
// mediaSource is "browser", "window" or "screen", or null for none.
// - The element is created on the first target, never before.
// - At most one capture runs: a new target stops the old one before it
//   starts, and a start that resolves after a newer setTarget or stop() is
//   stopped unless a newer start already replaced it.
// - setTarget(null) stops the capture and hides the element at once.
// - stop() is final: it removes the element and later calls do nothing.
// - With `enabled` false nothing is created or started (previews turned off,
//   as in Zen's prompt).
// - It writes no permission.
// isLive() is true from a start until the next stop. hasFrame() is true only
// while live and the element's video has a frame (a non-zero width): a start
// that macOS refuses can stay live with no frame.
export function startLive(win, container, { enabled = true } = {}) {
  let el = null;
  let target = null;
  let gen = 0;
  let startedGen = 0;
  let live = false;
  let stopped = !enabled;

  function halt() {
    live = false;
    try {
      el?.stopPreview?.();
    } catch {
      // The element may not be upgraded yet; nothing runs then.
    }
  }

  function same(a, b) {
    if (a === null || b === null) {
      return a === b;
    }
    return a.deviceId === b.deviceId && a.mediaSource === b.mediaSource;
  }

  return {
    async setTarget(next) {
      next = next ?? null;
      if (stopped || same(next, target)) {
        return;
      }
      const mine = ++gen;
      target = next && { deviceId: next.deviceId, mediaSource: next.mediaSource };
      halt();
      if (target === null) {
        if (el) {
          el.hidden = true;
        }
        return;
      }
      if (!el) {
        el = win.document.createElement("webrtc-preview");
        el.classList.add("zsp-live");
        container.append(el);
      }
      el.hidden = false;
      const { deviceId, mediaSource } = target;
      try {
        await el.updateComplete;
        if (stopped || mine !== gen) {
          return;
        }
        startedGen = mine;
        live = true;
        await el.startPreview({
          deviceId,
          mediaSource,
          showPreviewControlButtons: false,
        });
        if ((stopped || mine !== gen) && startedGen === mine) {
          halt();
        }
      } catch {
        if (!stopped && mine === gen) {
          halt();
          el.hidden = true;
        } else if (startedGen === mine) {
          halt();
        }
      }
    },
    stop() {
      if (stopped) {
        return;
      }
      stopped = true;
      gen++;
      target = null;
      halt();
      el?.remove();
    },
    isLive() {
      return live;
    },
    hasFrame() {
      if (!live || !el || el.hidden) {
        return false;
      }
      try {
        return (el.videoEl?.videoWidth ?? 0) > 0;
      } catch {
        return false;
      }
    },
  };
}

// P71: how long the highlight rests on a row before its live capture starts.
export const LIVE_DWELL_MS = 150;

// Feeds targets to apply(target) after a dwell, so a highlight that only
// passes over rows starts no capture. A new target stops the applied one at
// once and is applied after `ms`, unless another comes first. A null target
// stops at once. cancel() drops a pending target. A Firefox capture can't be
// cancelled once requested, so it is better never to request it.
export function dwellTargets(win, apply, ms) {
  let timer = null;
  let applied = null;

  function cancel() {
    if (timer !== null) {
      win.clearTimeout(timer);
      timer = null;
    }
  }

  function put(target) {
    applied = target;
    apply(target);
  }

  return {
    set(target) {
      cancel();
      if (applied !== null) {
        put(null);
      }
      if (target === null) {
        return;
      }
      timer = win.setTimeout(() => {
        timer = null;
        put(target);
      }, ms);
    },
    cancel,
  };
}

// The live preview's target for the picker's model and state: the highlighted
// window or screen, only while the Windows view shows and that row is
// visible, else null. Feeding every state change through
// setTarget(liveTarget(model, state)) stops a capture at once when the view
// switches to Tabs, the highlight moves or hides, or a new model drops the
// row.
export function liveTarget(model, state) {
  if (state.view !== "windows" || state.windowHighlight === null) {
    return null;
  }
  const key = state.windowHighlight;
  if (!visibleRows(model, state).some(r => r.key === key)) {
    return null;
  }
  const row = model.captures.find(r => r.key === key);
  if (!row || (row.kind !== "window" && row.kind !== "screen")) {
    return null;
  }
  return { deviceId: row.deviceId, mediaSource: row.kind };
}
