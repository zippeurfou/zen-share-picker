const UNTITLED = "Untitled window";

function toRow(kind, e) {
  return {
    key: kind + ":" + e.deviceId,
    deviceId: e.deviceId,
    kind,
    title: kind === "window" && e.label === "" ? UNTITLED : e.label,
    host: "",
    group: "capture",
  };
}

// Screens first, then windows, each in Zen's order. The OS entry, tabs and
// other sources are not rows. A window is hidden when it is one of Zen's own
// (P50), or when Zen's ids are unknown: then every window is. Anything but
// `ok` exactly true with a Set of ids is unknown.
export function captureRows(entries, osDeviceId, zen) {
  const known = zen?.ok === true && zen.ids instanceof Set;
  const screens = [];
  const windows = [];
  let hidden = 0;
  for (const e of entries) {
    if (e.mediaSource !== "screen" && e.mediaSource !== "window") {
      continue;
    }
    if (osDeviceId !== null && e.deviceId === osDeviceId) {
      continue;
    }
    if (e.mediaSource === "screen") {
      screens.push(toRow("screen", e));
      continue;
    }
    if (!known || zen.ids.has(e.deviceId)) {
      hidden++;
      continue;
    }
    windows.push(toRow("window", e));
  }
  return { rows: [...screens, ...windows], hidden };
}
