import { matches } from "./rows.mjs";

const HINT_REVEAL = "Tab: show tabs from your other spaces";
const HINT_NO_MATCH = "No match here. Tab to search other spaces.";
const HINT_ASLEEP =
  "Don't see a tab? Tabs that are asleep can't be shared; open it first.";
// P72: Zen's own warning for a screen, which the hidden prompt no longer shows.
const HINT_SCREEN = "Careful: everything on this screen will be visible.";

export function hasTabs(model) {
  return model.here.length > 0 || model.others.some(g => g.rows.length > 0);
}

export function windowRows(model) {
  return model.os.available ? [...model.captures, model.os] : [...model.captures];
}

export function hasWindows(model) {
  return windowRows(model).length > 0;
}

export function initialState(model) {
  const first = model.here.find(r => !r.requesting);
  return {
    query: "",
    revealed: false,
    highlight: first ? first.key : null,
    confirming: null,
    view: !hasTabs(model) && hasWindows(model) ? "windows" : "tabs",
    windowHighlight: null,
  };
}


function tabRows(model, state) {
  const rows = model.here.filter(r => matches(r, state.query));
  if (state.revealed) {
    for (const g of model.others) {
      rows.push(...g.rows.filter(r => matches(r, state.query)));
    }
  }
  return rows;
}

// P52: the OS row lives in the Windows tab only.
export function visibleRows(model, state) {
  if (state.view === "windows") {
    return windowRows(model).filter(r => r.key === model.os.key || matches(r, state.query));
  }
  return tabRows(model, state);
}

function findWindowRow(model, key) {
  if (key === model.os.key && model.os.available) {
    return { kind: "os" };
  }
  const row = model.captures.find(r => r.key === key);
  return row ? { kind: "capture", row } : null;
}

function findRow(model, key) {
  const here = model.here.find(r => r.key === key);
  if (here) {
    return { kind: "here", row: here };
  }
  for (const g of model.others) {
    const row = g.rows.find(r => r.key === key);
    if (row) {
      return { kind: "other", row };
    }
  }
  return null;
}

export function hints(model, state) {
  if (state.view === "windows") {
    const key = state.windowHighlight;
    const row = model.captures.find(r => r.key === key);
    const shown = row && visibleRows(model, state).some(r => r.key === key);
    return shown && row.kind === "screen" ? [{ code: "screen", text: HINT_SCREEN }] : [];
  }
  const out = [];
  if (!hasTabs(model)) {
    out.push({ code: "no-tabs", text: "There are no tabs to share here." });
  }
  const hasOthers = model.others.some(g => g.rows.length > 0);
  if (!state.revealed && hasOthers) {
    const emptyQuery = state.query.trim() === "";
    const hereMatch = model.here.some(r => matches(r, state.query));
    if (emptyQuery || hereMatch) {
      out.push({ code: "reveal", text: HINT_REVEAL });
    } else {
      out.push({ code: "no-match", text: HINT_NO_MATCH });
    }
  }
  if (state.confirming !== null) {
    const found = findRow(model, state.confirming);
    if (found && found.kind === "other") {
      out.push({
        code: "confirm",
        text: `Press Enter again to share a tab from ${found.row.spaceLabel}.`,
      });
    }
  }
  out.push({ code: "asleep", text: HINT_ASLEEP });
  return out;
}

function move(model, state, key) {
  const keys = visibleRows(model, state).map(r => r.key);
  if (keys.length === 0) {
    return null;
  }
  const current = state.view === "windows" ? state.windowHighlight : state.highlight;
  const idx = current === null ? -1 : keys.indexOf(current);
  let next;
  if (key === "Home") {
    next = 0;
  } else if (key === "End") {
    next = keys.length - 1;
  } else if (idx === -1) {
    next = 0;
  } else if (key === "ArrowDown") {
    next = Math.min(idx + 1, keys.length - 1);
  } else {
    next = Math.max(idx - 1, 0);
  }
  return keys[next];
}

function enterWindow(model, state) {
  const cleared = { ...state, confirming: null };
  const key = state.windowHighlight;
  if (key === null || !visibleRows(model, state).some(r => r.key === key)) {
    return { state: cleared, effect: null };
  }
  const found = findWindowRow(model, key);
  if (!found) {
    return { state: cleared, effect: null };
  }
  if (found.kind === "os") {
    return { state: cleared, effect: { type: "os" } };
  }
  const { kind, deviceId } = found.row;
  return { state: cleared, effect: { type: "share", kind, deviceId } };
}

function enter(model, state) {
  if (state.view === "windows") {
    return enterWindow(model, state);
  }
  const cleared = { ...state, confirming: null };
  if (state.highlight === null) {
    return { state: cleared, effect: null };
  }
  const visible = visibleRows(model, state).some(r => r.key === state.highlight);
  const found = visible ? findRow(model, state.highlight) : null;
  if (!found) {
    return { state: cleared, effect: null };
  }
  if (found.kind === "here" || state.confirming === state.highlight) {
    return {
      state: cleared,
      effect: { type: "share", kind: "tab", deviceId: found.row.deviceId },
    };
  }
  return { state: { ...state, confirming: state.highlight }, effect: null };
}

// The Tabs highlight for `next`: kept while visible, else the first visible
// tab that is not the requesting one.
function seedTabs(model, next) {
  const rows = visibleRows(model, next);
  if (next.highlight !== null && rows.some(r => r.key === next.highlight)) {
    return next;
  }
  const first = rows.find(r => r.key !== model.os.key && !r.requesting);
  return { ...next, highlight: first ? first.key : null };
}

export function reduce(model, state, action) {
  switch (action.type) {
    case "switch": {
      if (action.view === state.view) {
        return { state, effect: null };
      }
      if (action.view === "windows" && !hasWindows(model)) {
        return { state, effect: null };
      }
      const next = {
        ...state,
        view: action.view,
        query: "",
        confirming: null,
        windowHighlight: null,
      };
      return { state: action.view === "tabs" ? seedTabs(model, next) : next, effect: null };
    }
    case "query": {
      const next = { ...state, query: action.text, confirming: null };
      const rows = visibleRows(model, next);
      if (state.view === "windows") {
        const kept = state.windowHighlight !== null && rows.some(r => r.key === state.windowHighlight);
        next.windowHighlight = kept ? state.windowHighlight : null;
        return { state: next, effect: null };
      }
      return { state: seedTabs(model, next), effect: null };
    }
    case "click":
      if (!visibleRows(model, state).some(r => r.key === action.key)) {
        return { state, effect: null };
      }
      if (state.view === "windows") {
        return {
          state: { ...state, windowHighlight: action.key, confirming: null },
          effect: null,
        };
      }
      return {
        state: { ...state, highlight: action.key, confirming: null },
        effect: null,
      };
    case "share":
      return enter(model, state);
    case "cancel":
      return {
        state: { ...state, confirming: null },
        effect: { type: "cancel" },
      };
    case "key":
      switch (action.key) {
        case "ArrowDown":
        case "ArrowUp":
        case "Home":
        case "End": {
          const field = state.view === "windows" ? "windowHighlight" : "highlight";
          return {
            state: {
              ...state,
              [field]: move(model, state, action.key),
              confirming: null,
            },
            effect: null,
          };
        }
        case "Tab":
          if (state.view === "windows") {
            return { state: { ...state, confirming: null }, effect: null };
          }
          return {
            state: { ...state, revealed: true, confirming: null },
            effect: null,
          };
        case "Enter":
          return enter(model, state);
        case "Escape":
          return {
            state: { ...state, confirming: null },
            effect: { type: "cancel" },
          };
        default:
          return { state: { ...state, confirming: null }, effect: null };
      }
    default:
      return { state, effect: null };
  }
}
