// P50: the ids of Zen's own top-level windows, as the share prompt's window
// entries carry them (webrtcUI.sys.mjs maps shared windows the same way).
// P70: `seen` holds the ids recorded at earlier reads of the same prompt;
// they stay in the answer, so a Zen window closed since stays Zen's.
// Never throws: when any read throws, the answer is unknown ({ok: false}),
// and the caller hides every window entry of the prompt.
export function zenWindowIds(Services, seen = null) {
  try {
    const ids = new Set(seen ?? []);
    for (const w of Services.wm.getEnumerator(null)) {
      ids.add(String(w.windowUtils.webrtcRawDeviceId));
    }
    return { ok: true, ids };
  } catch {
    return { ok: false };
  }
}
