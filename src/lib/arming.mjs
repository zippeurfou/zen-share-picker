// When the picker takes a choice (P33). An explicit choice is input received
// once security.notification_enable_delay has passed since the picker opened
// or its window was last activated, as PopupNotifications does for its own
// buttons. An auto-repeat or an untrusted event never commits.
//
// `times` is { openedAt, activatedAt, delayMs }: ms on one clock
// (ChromeUtils.now()), activatedAt null until the window is activated again.

// The pref's value, or `fallback` when it is not a number. A user-set 0 is
// kept: the picker then arms at once, as the stock prompt does.
export function delayOf(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : fallback;
}

// The time the picker arms; NaN when a time is unreadable.
export function armsAt(times) {
  if (!times) {
    return NaN;
  }
  const { openedAt, activatedAt = null, delayMs } = times;
  const since = activatedAt === null ? openedAt : Math.max(openedAt, activatedAt);
  return since + delayMs;
}

// False whenever a time is unreadable, so nothing commits.
export function isArmed(times, now) {
  return now >= armsAt(times);
}

// Enter and Share commit a choice; Enter on the OS row commits it too.
export function isCommit(action) {
  return action.type === "share" || (action.type === "key" && action.key === "Enter");
}

// Esc and Cancel decline the request (P36). They are not commits, so arming
// never gates them.
export function isCancel(action) {
  return action.type === "cancel" || (action.type === "key" && action.key === "Escape");
}

// Whether the overlay may dispatch `action`, from an event with `trusted`
// (isTrusted) and `repeat`. A cancel needs a trusted event that is not an
// auto-repeat; a commit also needs arming; anything else always may.
export function mayDispatch(action, { trusted, repeat } = {}, times, now) {
  if (isCancel(action)) {
    return trusted === true && repeat !== true;
  }
  if (!isCommit(action)) {
    return true;
  }
  return trusted === true && repeat !== true && isArmed(times, now);
}
