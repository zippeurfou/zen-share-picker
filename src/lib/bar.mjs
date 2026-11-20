// The sharing bar's pure logic: its label, the keys of the shares it shows,
// where it sits and the colors derived from the accent.
//
// It reads only a stream's id, its URI and its devices' kinds (mediaSource
// and scary), never a title or any other field, so a tab or window title can
// never reach the label.

const VERBS = {
  screen: "Sharing your entire screen",
  "zen-window": "Sharing a Zen window",
  tab: "Sharing a tab",
  window: "Sharing a window",
};

const PRECEDENCE = ["screen", "zen-window", "tab", "window"];

// The kind a device counts as, or null when the bar's label ignores it.
function deviceKind(device) {
  const source = device.mediaSource;
  if (source === "screen") {
    return "screen";
  }
  if (source === "window") {
    return device.scary ? "zen-window" : "window";
  }
  if (source === "application") {
    return "window";
  }
  if (source === "browser") {
    return "tab";
  }
  return null;
}

function webHost(uri) {
  try {
    const url = new URL(uri);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.hostname || "";
    }
  } catch {
    // Not a URL: no host.
  }
  return "";
}

export function barLabel(streams) {
  const kinds = new Set();
  const hosts = new Set();
  let hostless = false;
  for (const stream of streams) {
    const devices = stream.devices ?? [];
    let counted = false;
    for (const device of devices) {
      const kind = deviceKind(device);
      if (kind) {
        kinds.add(kind);
        counted = true;
      }
    }
    if (counted) {
      const host = webHost(stream.uri);
      if (host) {
        hosts.add(host);
      } else {
        hostless = true;
      }
    }
  }
  const kind = PRECEDENCE.find((k) => kinds.has(k)) ?? null;
  if (!kind) {
    return { kind: null, verb: "", site: "", text: "" };
  }
  const site = !hostless && hosts.size === 1 ? [...hosts][0] : "";
  const verb = site ? `${VERBS[kind]} with` : VERBS[kind];
  return { kind, verb, site, text: site ? `${verb} ${site}` : verb };
}

export function shareKeys(streams) {
  const keys = new Set();
  for (const stream of streams) {
    for (const device of stream.devices ?? []) {
      if (deviceKind(device)) {
        keys.add(`${stream.id}|${device.mediaSource}`);
      }
    }
  }
  return keys;
}

export function hasNewShare(remembered, current) {
  for (const key of current) {
    if (!remembered.has(key)) {
      return true;
    }
  }
  return false;
}

export function pruneKeys(remembered, current) {
  return new Set([...remembered].filter((key) => current.has(key)));
}

export const GAP_SELECTED = 88;
export const GAP_OTHER = 16;

function centerX(content, size) {
  return Math.round(content.x + (content.width - size.width) / 2);
}

// `lo` when the span doesn't fit, so the left or top edge stays visible.
function clamp(value, lo, span, size) {
  return Math.max(lo, Math.min(value, Math.round(lo + span - size)));
}

// With `screen` ({left, top, width, height}), the whole window, margin
// included, stays inside it.
export function barPosition({ content, size, selected, margin, screen }) {
  const gap = selected ? GAP_SELECTED : GAP_OTHER;
  const x = centerX(content, size);
  const y = Math.round(content.y + content.height - gap - size.height + margin);
  if (!screen) {
    return { x, y };
  }
  return {
    x: clamp(x, screen.left, screen.width, size.width),
    y: clamp(y, screen.top, screen.height, size.height),
  };
}

// Firefox's own spot for the bar: centered at the top of the content.
export function topCenter({ content, size }) {
  return { x: centerX(content, size), y: Math.round(content.y) };
}

export function isUserMove(expected, actual, tol = 2) {
  if (!expected) {
    return false;
  }
  return Math.abs(actual.x - expected.x) > tol || Math.abs(actual.y - expected.y) > tol;
}

// 260 px is the grip, icon, divider and both buttons.
export function labelMaxPx(contentWidth) {
  return Math.min(720, Math.max(120, Math.round(contentWidth * 0.9) - 260));
}

const RGB =
  /^rgba?\(\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)\s*(?:[,/]\s*[\d.]+%?\s*)?\)$/i;

export function parseRgb(css) {
  if (typeof css !== "string") {
    return null;
  }
  const m = RGB.exec(css.trim());
  if (!m) {
    return null;
  }
  const rgb = [m[1], m[2], m[3]].map((v) => Math.round(Number(v)));
  return rgb.every((v) => v >= 0 && v <= 255) ? rgb : null;
}

function linear(channel) {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance([r, g, b]) {
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

export function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const WHITE = [255, 255, 255];
const BLACK = [0, 0, 0];
const DARK_TEXT = [0x16, 0x13, 0x2a];
const SURFACE_LIGHT = [0xf7, 0xf7, 0xf8];
const SURFACE_DARK = [0x2a, 0x2a, 0x2e];

// Moves each channel of `c` by fraction `t` toward `toward`, rounded.
function mix(c, t, toward) {
  return c.map((v, i) => Math.round(v + (toward[i] - v) * t));
}

function hex(rgb) {
  return `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

// The smallest step i (t = i / 100) in [0, maxStep] for which `ok(t)` holds,
// or -1.
function firstStep(maxStep, ok) {
  for (let i = 0; i <= maxStep; i++) {
    if (ok(i / 100)) {
      return i;
    }
  }
  return -1;
}

export function accentTokens(accent, dark) {
  const surface = dark ? SURFACE_DARK : SURFACE_LIGHT;

  let fillText = WHITE;
  let toward = BLACK;
  let step = firstStep(25, (t) => contrast(WHITE, mix(accent, t, BLACK)) >= 4.5);
  if (step < 0) {
    fillText = DARK_TEXT;
    toward = WHITE;
    step = firstStep(100, (t) => contrast(DARK_TEXT, mix(accent, t, WHITE)) >= 4.5);
    if (step < 0) {
      step = 100;
    }
  }
  const fillAt = (s) => mix(accent, Math.min(100, s) / 100, toward);

  const alphas = dark ? [0.16, 0.22, 0.28] : [0.12, 0.18, 0.24];
  const [tint, tintHover, tintPressed] = alphas.map((a) => mix(surface, a, accent));

  const inkToward = dark ? WHITE : BLACK;
  const inkAt = (s) => mix(accent, Math.min(100, s) / 100, inkToward);
  let inkStep = firstStep(100, (t) => contrast(mix(accent, t, inkToward), tint) >= 4.5);
  if (inkStep < 0) {
    inkStep = 100;
  }
  let strongStep = firstStep(100, (t) => contrast(mix(accent, t, inkToward), tintPressed) >= 4.5);
  if (strongStep < 0) {
    strongStep = 100;
  }
  strongStep = Math.max(strongStep, inkStep + 10);

  return {
    accent: hex(accent),
    fill: hex(fillAt(step)),
    fillHover: hex(fillAt(step + 10)),
    fillPressed: hex(fillAt(step + 20)),
    fillText: hex(fillText),
    tint: hex(tint),
    tintHover: hex(tintHover),
    tintPressed: hex(tintPressed),
    ink: hex(inkAt(inkStep)),
    inkStrong: hex(inkAt(strongStep)),
  };
}
