// The picker's preview of the highlighted tab. Both loops capture only the
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
// shows its selected entry. At most one capture runs: setTarget stops the
// previous one first.
export function startLive(win, container) {
  const el = win.document.createElement("webrtc-preview");
  el.classList.add("zsp-live");
  container.append(el);
  let target = null;
  let gen = 0;
  let stopped = false;

  function halt() {
    try {
      el.stopPreview?.();
    } catch {
      // The element may not be upgraded yet; nothing runs then.
    }
  }

  return {
    async setTarget(deviceId) {
      if (stopped || deviceId === target) {
        return;
      }
      const mine = ++gen;
      target = deviceId ?? null;
      halt();
      el.hidden = target === null;
      if (target === null) {
        return;
      }
      try {
        await el.updateComplete;
        if (stopped || mine !== gen) {
          return;
        }
        await el.startPreview({
          deviceId: target,
          mediaSource: "browser",
          showPreviewControlButtons: false,
        });
        if (stopped || mine !== gen) {
          halt();
        }
      } catch {
        halt();
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
      el.remove();
    },
  };
}
