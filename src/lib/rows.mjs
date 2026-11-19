const OS_LABEL_MACOS = "Open the macOS picker (apps, windows or a screen)";
const OS_LABEL = "Open the system picker (apps, windows or a screen)";

export function belongsHere(t, here) {
  if (here.spaceId === null) {
    return false;
  }
  if (t.essential) {
    return t.ucid !== null && t.ucid === here.ucid;
  }
  return t.spaceId !== null && t.spaceId === here.spaceId;
}

function rank(t) {
  if (t.contentsVisible) {
    return 0;
  }
  if (t.inPromptWindow) {
    return 1;
  }
  return 2;
}

function better(a, b) {
  const ra = rank(a);
  const rb = rank(b);
  if (ra !== rb) {
    return ra < rb;
  }
  return a.lastAccessed > b.lastAccessed;
}

export function dedupe(facts) {
  const kept = new Map();
  const requesting = new Set();
  for (const t of facts) {
    if (t.requesting) {
      requesting.add(t.syncKey);
    }
    const cur = kept.get(t.syncKey);
    if (!cur || better(t, cur)) {
      kept.set(t.syncKey, t);
    }
  }
  return [...kept.values()].map(t => ({
    ...t,
    requesting: requesting.has(t.syncKey),
  }));
}

function byRecency(a, b) {
  if (a.requesting !== b.requesting) {
    return a.requesting ? 1 : -1;
  }
  return b.lastAccessed - a.lastAccessed;
}

function toRow(t, group, spaceLabel) {
  return {
    key: t.syncKey,
    deviceId: t.deviceId,
    title: t.title,
    host: t.host,
    icon: t.icon,
    group,
    spaceLabel,
    requesting: t.requesting,
  };
}

export function buildModel(facts, here, spaceNames, os, captures = []) {
  const tabs = dedupe(facts);
  const hereFacts = [];
  const groups = new Map();
  for (const t of tabs) {
    if (belongsHere(t, here)) {
      hereFacts.push(t);
      continue;
    }
    let id;
    let label;
    if (t.essential) {
      id = "essential:" + t.ucid;
      label = "Essentials";
    } else {
      id = "space:" + t.spaceId;
      label = (t.spaceId !== null && spaceNames.get(t.spaceId)) || "Other space";
    }
    if (!groups.has(id)) {
      groups.set(id, { label, facts: [] });
    }
    groups.get(id).facts.push(t);
  }
  const others = [...groups.values()]
    .map(g => {
      g.facts.sort(byRecency);
      return {
        label: g.label,
        recent: Math.max(...g.facts.map(t => t.lastAccessed)),
        rows: g.facts.map(t => toRow(t, "other", g.label)),
      };
    })
    .sort((a, b) => b.recent - a.recent)
    .map(({ label, rows }) => ({ label, rows }));
  return {
    here: hereFacts.sort(byRecency).map(t => toRow(t, "here", null)),
    others,
    os: {
      key: "os",
      label: os.macos ? OS_LABEL_MACOS : OS_LABEL,
      available: !!os.available,
    },
    captures,
  };
}

export function matches(row, query) {
  const q = query.trim().toLowerCase();
  if (q === "") {
    return true;
  }
  return (
    row.title.toLowerCase().includes(q) || row.host.toLowerCase().includes(q)
  );
}
