import { useEffect, useState } from "react";
import { canCall, onSession } from "../api/session";

/* Whether this caller may call a tool, as a hook so a squad change re-renders.
 *
 * Used to decide what to offer, never to decide what is allowed — that is the
 * gateway's job, on every request. Hiding a control the platform would refuse
 * is politeness; the refusal is still the thing that enforces it.
 */
export function useCan(tool: string): boolean {
  const [allowed, setAllowed] = useState(() => canCall(tool));
  useEffect(() => onSession(() => setAllowed(canCall(tool))), [tool]);
  return allowed;
}
