/* Which squad this session is looking through.
 *
 * A squad is the isolation boundary: it decides which cache directory the
 * engine is started against, so it cannot be inferred after the fact. One
 * squad means nothing to choose and the control stays out of the way; several
 * means the choice has to be made, because the gateway will otherwise refuse
 * the request and say so.
 */

import type { Session } from "../api/session";

interface Props {
  session: Session;
  onChoose: (squad: string) => void;
}

export function SquadPicker({ session, onChoose }: Props) {
  if (session.squads.length <= 1) {
    return session.squad ? (
      <span className="text-[11px] text-muted-foreground/70 font-mono">{session.squad}</span>
    ) : null;
  }

  return (
    <select
      value={session.squad ?? ""}
      onChange={(event) => onChoose(event.target.value)}
      title="Squad"
      className="px-2 py-1 rounded-md bg-white/[0.04] border border-border/30
                 text-[11px] text-foreground/80 outline-none focus:border-primary/50"
    >
      {!session.squad && <option value="">choose a squad…</option>}
      {session.squads.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}
