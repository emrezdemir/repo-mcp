import { useEffect } from "react";

/* Escape closes whatever is open.
 *
 * A dialog that can only be dismissed by finding the right place to click is a
 * dialog people get stuck in — and anyone navigating by keyboard has no way
 * out at all. This is the one line that fixes both, so it lives somewhere
 * every dialog can reach it.
 */
export function useDismiss(active: boolean, dismiss: () => void): void {
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        dismiss();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, dismiss]);
}
