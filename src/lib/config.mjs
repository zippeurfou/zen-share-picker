// Modes and timings, as decided by the platform tests in
// tests/acceptance/test_platform.py against Zen 1.24.2b.

// test_stock_share_flow and test_overlay_keeps_the_prompt_open_and_active: Allow takes a timed click.
export const SHARE_MODE = "click";
// test_background_tab_snapshot: captureTabPreviewThumbnail paints background and other-space tabs.
export const PREVIEW_MODE = "snapshot";
// test_overlay_keeps_the_prompt_open_and_active: WebDriver key actions reach a focused chrome input.
export const KEY_INPUT = "webdriver";

export const TIMING = Object.freeze({
  // test_background_tab_snapshot: a capture takes a few ms, so once a second is cheap.
  snapshotMs: 1000,
  // test_stock_share_flow: how long the window may take to be active before falling back to assist.
  allowWindowMs: 5000,
  // test_stock_share_flow: the notification went within 10 ms of an accepted click.
  goneWaitMs: 1000,
  // test_stock_share_flow: the page had its stream well within 5 s.
  verifyMs: 5000,
  // test_stock_share_flow: the poll step of every wait above.
  pollMs: 50,
  // test_stock_share_flow: a click the delay rejects pushes the delay back, so at most one retry.
  maxClicks: 2,
  // test_stock_share_flow: security.notification_enable_delay when the pref cannot be read.
  defaultDelayMs: 500,
});
