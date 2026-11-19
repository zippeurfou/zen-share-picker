// The picker's header (P37). Zen's share prompt, which named the asking
// site, is hidden while the picker is open, so the header names it, in the
// words of Zen's own prompt (webrtcIndicator.ftl). The caller sets the text
// with textContent only.

const named = v => (typeof v === "string" && v !== "" ? v : null);

export function headerText(site) {
  if (site === null || site === undefined) {
    return "Choose what to share";
  }
  const name = named(site.name);
  const secondName = named(site.secondName);
  if (name === null) {
    // Zen shows no origin for a local file (WebRTCParent.sys.mjs).
    return "This local file wants to see your screen";
  }
  if (secondName !== null) {
    return `${name} wants to give ${secondName} permission to see your screen`;
  }
  return `${name} wants to see your screen`;
}
