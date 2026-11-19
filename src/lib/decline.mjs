// The decline sequence (P36, P38) as pure logic over a port and a Clock.
//
// The only call to port.abandon() in the add-on is here. api.js runs
// runDecline for a cancel effect, and the overlay sends one only for a
// trusted, non-repeat Esc or click on Cancel. abandon() removes the
// session's own notification the way Zen abandons a request: WebRTC denies
// it and sets no permission. It is made at most once, right after, in the
// same synchronous step, a check that the prompt is still the session's own.
//
// reveal() shows Zen's panel again. It runs exactly once, right after the
// first check that the notification is gone, so a queued notification never
// opens under this session's hiding.
//
// Outcomes:
//   "declined"  the notification went after the abandon
//   "kept"      the prompt was no longer the session's own; nothing done
//   "failed"    the abandon threw or the notification stayed; the user
//               decides in Zen's prompt

export async function runDecline({ port, clock, timing, log, reveal }) {
  let revealed = false;
  const show = () => {
    if (!revealed) {
      revealed = true;
      try {
        reveal();
      } catch {
        // The caller shows the panel again when the sequence settles.
      }
    }
  };
  let threw = false;
  try {
    if (!port.isCurrent()) {
      show();
      log("decline: kept not-current");
      return "kept";
    }
    log("decline: abandon");
    try {
      port.abandon();
    } catch (e) {
      threw = true;
      log("decline: error " + (e?.name ?? "error"));
    }
    const end = clock.now() + timing.goneWaitMs;
    const gone = port.isGone();
    show();
    if (gone) {
      log("decline: declined");
      return "declined";
    }
    while (clock.now() < end) {
      await clock.sleep(timing.pollMs);
      if (port.isGone()) {
        log("decline: declined");
        return "declined";
      }
    }
    log("decline: failed " + (threw ? "error" : "not-gone"));
    return "failed";
  } catch (e) {
    show();
    log("decline: error " + (e?.name ?? "error"));
    log("decline: failed error");
    return "failed";
  }
}
