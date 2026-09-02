/** Whether the assistant panel is open — one answer, read by two components.
 *
 *  It lives in `localStorage` rather than in React state because it has to survive a
 *  navigation, and it is read through `useSyncExternalStore` because that is what state
 *  outside React is for: a lazy `useState` initialiser cannot be used (the server has no
 *  `localStorage`, so it would render one value and hydrate to another), and setting it
 *  from an effect meant a synchronous `setState` on every mount.
 *
 *  It moved out of the panel component when the open control moved to the top bar. The
 *  trigger and the panel are now separate components on opposite sides of the layout,
 *  and both need the same answer — a second copy of "is it open" is a panel that
 *  disagrees with its own button.
 */

const STORAGE_KEY = "datapond_assistant_open"

const listeners = new Set<() => void>()

/** Subscribe to changes. Returns the unsubscribe, as `useSyncExternalStore` expects. */
export function subscribeToPanelState(onChange: () => void) {
  listeners.add(onChange)
  return () => { listeners.delete(onChange) }
}

/** Open only when explicitly stored as open: an absent key, "0", or anything else is
 *  closed. A first visit therefore starts closed rather than with a panel nobody asked
 *  for. */
export function readPanelOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    // A browser with site data blocked throws on access. The panel is a convenience;
    // failing to read its last state must not take the page down with it.
    return false
  }
}

/** The server has no `localStorage`, so it always renders the closed state and hydrates
 *  to whatever the browser then reports. */
export function serverPanelOpen(): boolean {
  return false
}

export function togglePanel(): void {
  try {
    localStorage.setItem(STORAGE_KEY, readPanelOpen() ? "0" : "1")
  } catch {
    // Same reasoning as readPanelOpen: a refused write leaves the panel where it is
    // rather than throwing out of a click handler.
    return
  }
  listeners.forEach(fn => fn())
}
