// The share sequence (design D1) as pure logic over a PromptPort and a Clock.
//
// The only call to port.clickAllow() in the add-on is here, and runShare runs
// only after an explicit Enter or a click on Share. Timers only delay that
// click. Every click is made right after, in the same synchronous step, a
// check that the prompt is the one the choice was made on, the choice is
// still selected, the window is active, Allow is enabled and the enable delay
// has passed.

// Outcomes:
//   "shared"      the prompt went after our click and the tab is being shared
//   "handed-off"  the prompt went after our click on the OS-picker entry
//   "assist"      the picker closed with the choice selected; the user presses Allow
//   "aborted"     nothing was clicked; the prompt was gone or the choice failed
//   "unverified"  the prompt went after our click, but no stream showed the
//                 tab; or something threw after a click
//
// Nothing ever runs a share again: "assist" means the user acts on the stock
// prompt.

export async function runShare({
  port,
  clock,
  mode,
  target,
  closePicker,
  stopPreview,
  timing,
  log,
}) {
  let closed = false;
  let clicks = 0;
  const close = () => {
    if (!closed) {
      closed = true;
      closePicker();
    }
  };
  // The picker's preview must stop before the stock prompt's starts.
  if (typeof stopPreview !== "function") {
    log("share: aborted no-stop-preview");
    try {
      close();
    } catch {
      // Nothing was selected; the outcome says so.
    }
    return "aborted";
  }
  try {
    return await sequence();
  } catch (e) {
    log("share: error " + (e?.name ?? "error"));
    // After a click the prompt may be gone: never ask for another Allow.
    if (clicks > 0) {
      return "unverified";
    }
    if (!closed) {
      try {
        port.restore();
      } catch {
        // The prompt is gone or broken; nothing else to put back.
      }
      try {
        close();
      } catch {
        // Nothing more to do; the outcome below says no click happened.
      }
      return "aborted";
    }
    return "assist";
  }

  async function sequence() {
    // 1. Stop the picker's own preview, so only one capture ever runs.
    stopPreview();
    if (!port.isCurrent()) {
      log("share: aborted not-current");
      close();
      return "aborted";
    }

    // 2. Select the choice in the stock dropdown, and read it back.
    const ok = port.select(target.deviceId, target.kind);
    if (!ok || port.selectedDeviceId() !== target.deviceId) {
      log("share: aborted " + (ok ? "readback" : "select"));
      port.restore();
      close();
      return "aborted";
    }

    // 3. Close, so the window and the panel are active again.
    close();
    if (mode === "assist") {
      log("share: assist mode");
      return "assist";
    }

    // 4. Wait for the enable delay and an active window, then click.
    const start = clock.now();
    while (clock.now() - start < timing.allowWindowMs) {
      if (!port.isCurrent()) {
        log("share: aborted not-current");
        return "aborted";
      }
      if (port.selectedDeviceId() !== target.deviceId) {
        log("share: assist selection-changed");
        return "assist";
      }
      if (!port.windowActive() || !port.allowEnabled()) {
        await clock.sleep(timing.pollMs);
        continue;
      }
      const since = port.msSinceShown();
      const delay = port.delayMs();
      if (!(since >= delay)) {
        const rest = Number.isFinite(delay - since) ? delay - since : 0;
        await clock.sleep(Math.max(0, rest) + timing.pollMs);
        continue;
      }
      port.clickAllow();
      clicks += 1;
      log("share: click " + clicks);
      const goneBy = clock.now() + timing.goneWaitMs;
      while (port.isCurrent() && clock.now() < goneBy) {
        await clock.sleep(timing.pollMs);
      }
      if (!port.isCurrent()) {
        return verify();
      }
      if (clicks >= timing.maxClicks) {
        log("share: assist click-rejected");
        return "assist";
      }
    }
    log("share: assist timeout");
    return "assist";
  }

  // 5. The prompt went after our click: check that the tab is shared.
  async function verify() {
    if (target.kind === "os") {
      log("share: handed-off");
      return "handed-off";
    }
    const end = clock.now() + timing.verifyMs;
    for (;;) {
      if (port.sharingShows(target.deviceId)) {
        log("share: shared");
        return "shared";
      }
      if (clock.now() >= end) {
        log("share: unverified");
        return "unverified";
      }
      await clock.sleep(timing.pollMs);
    }
  }
}
