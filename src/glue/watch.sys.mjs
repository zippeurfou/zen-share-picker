// Runs a setup in every browser window once its delayed startup finished,
// now and later, and undoes it on stop() or when the window unloads.
//
// watchWindows({ Services, onWindow(win): () => void }) -> { stop() }
// `onWindow` returns the window's uninstall. A throwing onWindow or
// uninstall is caught, so one window never stops the others.

const TOPIC = "browser-delayed-startup-finished";

export function watchWindows({ Services, onWindow }) {
  // win -> { uninstall, onUnload }
  const installed = new Map();
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
      console.error(`[zen-share-picker] uninstall failed: ${e?.name ?? "error"}`);
    }
  }

  function watch(win) {
    if (
      stopped ||
      installed.has(win) ||
      win.closed ||
      !win.gBrowserInit?.delayedStartupFinished
    ) {
      return;
    }
    let uninstall;
    try {
      uninstall = onWindow(win);
    } catch (e) {
      console.error(`[zen-share-picker] install failed: ${e?.name ?? "error"}`);
      return;
    }
    const onUnload = () => undo(win);
    installed.set(win, {
      uninstall: typeof uninstall === "function" ? uninstall : () => {},
      onUnload,
    });
    win.addEventListener("unload", onUnload, { once: true });
  }

  const observer = {
    observe(win, topic) {
      if (topic === TOPIC) {
        watch(win);
      }
    },
  };
  Services.obs.addObserver(observer, TOPIC);
  for (const win of Services.wm.getEnumerator("navigator:browser")) {
    watch(win);
  }

  return {
    stop() {
      if (stopped) {
        return;
      }
      stopped = true;
      Services.obs.removeObserver(observer, TOPIC);
      for (const win of [...installed.keys()]) {
        undo(win);
      }
    },
  };
}
