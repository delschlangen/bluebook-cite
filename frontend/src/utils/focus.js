// When the control a person pressed disappears (the Cancel of an upload, the file box that was
// hidden), the browser leaves focus on the page itself, and a keyboard or screen-reader user starts
// again from the top. These put it somewhere useful, but only when it really was lost: focus that
// is on something the person can still use is never moved.

/** True when focus is on nothing: the page, nothing, something taken out of the page, or hidden. */
export function focusIsLost() {
  const active = window.document.activeElement;
  return !active || active === window.document.body || !active.isConnected || Boolean(active.closest?.('[hidden]'));
}

/** Focus `element` if focus was lost. Returns whether it did. */
export function focusIfLost(element) {
  if (!element || !focusIsLost()) return false;
  element.focus();
  return true;
}
