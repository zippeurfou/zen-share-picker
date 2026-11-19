"use strict";

const $ = id => document.getElementById(id);
const REFRESH_MS = 2000;

let busy = false;

function render(status) {
  const state = $("state");
  state.textContent = status.state;
  state.dataset.state = status.state;
  $("version").textContent = status.version;
  $("share-mode").textContent = status.shareMode;
  $("preview-mode").textContent = status.previewMode;
  $("last-outcome").textContent = status.lastOutcome ?? "none";
  $("problems").textContent = status.promptProblems.length
    ? status.promptProblems.join(", ")
    : "none";

  $("failed").textContent = status.failedChecks.join(", ");
  $("failed-box").hidden = status.failedChecks.length === 0;

  $("enabled").checked = status.state === "active";
  $("enabled").disabled = busy || status.state === "starting";
  $("debug").checked = status.debug;
  $("debug").disabled = busy;
}

async function refreshStatus() {
  render(await browser.sharePicker.getStatus());
}

async function refreshLog() {
  const lines = await browser.sharePicker.getLog();
  const log = $("log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
  log.textContent = lines.join("\n");
  if (atBottom) {
    log.scrollTop = log.scrollHeight;
  }
}

async function run(action) {
  busy = true;
  $("enabled").disabled = true;
  $("debug").disabled = true;
  try {
    await action();
  } catch (e) {
    $("state").textContent = `error: ${e?.name ?? "error"}`;
  } finally {
    busy = false;
    await refreshStatus().catch(() => {});
  }
}

$("enabled").addEventListener("change", event => {
  const on = event.target.checked;
  run(() => browser.sharePicker.setEnabled(on));
});

$("debug").addEventListener("change", event => {
  const on = event.target.checked;
  run(async () => {
    await browser.sharePicker.setDebug(on);
    await refreshLog();
  });
});

refreshStatus().catch(e => {
  $("state").textContent = `error: ${e?.name ?? "error"}`;
});
refreshLog().catch(() => {});
setInterval(() => {
  if (!busy) {
    refreshStatus().catch(() => {});
    if ($("debug").checked) {
      refreshLog().catch(() => {});
    }
  }
}, REFRESH_MS);
