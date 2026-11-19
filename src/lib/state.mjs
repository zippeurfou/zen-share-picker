import { matches } from "./rows.mjs";

const HINT_REVEAL = "Tab: show tabs from your other spaces";
const HINT_NO_MATCH = "No match here. Tab to search other spaces.";
const HINT_ASLEEP =
  "Don't see a tab? Tabs that are asleep can't be shared; open it first.";

export function initialState(model) {
  const first = model.here.find(r => !r.requesting);
  return {
    query: "",
    revealed: false,
    highlight: first ? first.key : null,
    confirming: null,
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

export function visibleRows(model, state) {
  return [...tabRows(model, state), model.os];
}

function findRow(model, key) {
  if (key === model.os.key) {
    return { kind: "os" };
  }
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
  const out = [];
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
  const idx = state.highlight === null ? -1 : keys.indexOf(state.highlight);
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

function enter(model, state) {
  const cleared = { ...state, confirming: null };
  if (state.highlight === null) {
    return { state: cleared, effect: null };
  }
  const visible = visibleRows(model, state).some(r => r.key === state.highlight);
  const found = visible ? findRow(model, state.highlight) : null;
  if (!found) {
    return { state: cleared, effect: null };
  }
  if (found.kind === "os") {
    return { state: cleared, effect: { type: "os" } };
  }
  if (found.kind === "here" || state.confirming === state.highlight) {
    return {
      state: cleared,
      effect: { type: "share", deviceId: found.row.deviceId },
    };
  }
  return { state: { ...state, confirming: state.highlight }, effect: null };
}

export function reduce(model, state, action) {
  switch (action.type) {
    case "query": {
      const next = { ...state, query: action.text, confirming: null };
      const rows = visibleRows(model, next);
      if (state.highlight !== null && rows.some(r => r.key === state.highlight)) {
        return { state: next, effect: null };
      }
      const first = rows.find(r => r.key !== model.os.key && !r.requesting);
      next.highlight = first ? first.key : null;
      return { state: next, effect: null };
    }
    case "click":
      if (!visibleRows(model, state).some(r => r.key === action.key)) {
        return { state, effect: null };
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
        case "End":
          return {
            state: {
              ...state,
              highlight: move(model, state, action.key),
              confirming: null,
            },
            effect: null,
          };
        case "Tab":
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
