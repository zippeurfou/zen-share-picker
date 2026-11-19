"use strict";

// Logs reason codes only: never a title, URL, host or image.
browser.sharePicker.start().then(
  status => {
    if (status.state !== "active") {
      console.error(
        "[zen-share-picker] not active:",
        status.state,
        JSON.stringify({ failedChecks: status.failedChecks, promptProblems: status.promptProblems })
      );
    }
  },
  error => console.error("[zen-share-picker] start failed:", error?.name ?? "error")
);
