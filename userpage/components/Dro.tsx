"use client";

import type { MachineSnapshot } from "@/lib/api";

const AXES = ["X", "Y", "Z"] as const;

/**
 * Digital readout.
 *
 * Work coordinates are the big number because that is what the operator set
 * zero in and thinks in; machine coordinates sit underneath because they are
 * what the travel limits are measured against. The columns are fixed-width
 * and the numbers fixed to three decimals so a digit rolling over does not
 * shove the whole readout sideways while you are watching it.
 */
export default function Dro({ snap }: { snap: MachineSnapshot | null }) {
  const connected = Boolean(snap?.conn.connected);
  const state = connected ? snap?.state ?? "—" : "Disconnected";
  const alarm = state.startsWith("Alarm");

  return (
    <div className="panel ticked p-5">
      <div className="flex items-center justify-between">
        <span className="tlabel">Position</span>
        <span
          className={`inline-flex items-center gap-2 border px-2.5 py-1 font-mono text-xs ${
            alarm
              ? "border-warn text-warn"
              : connected
              ? "border-line-strong text-ink"
              : "border-line text-faint"
          }`}
        >
          {state}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-px bg-line">
        {AXES.map((axis, i) => (
          <div key={axis} className="bg-panel px-3 py-3">
            <span className="tlabel">{axis}</span>
            <p className="mt-1 font-mono text-2xl tabular-nums text-ink">
              {connected && snap ? snap.wpos[i].toFixed(3) : "—.———"}
            </p>
            <p className="font-mono text-[0.7rem] tabular-nums text-faint">
              mpos {connected && snap ? snap.mpos[i].toFixed(3) : "—.———"}
            </p>
          </div>
        ))}
      </div>

      {snap?.alarm && (
        <p className="mt-3 font-mono text-xs text-warn">{snap.alarm}</p>
      )}
      {snap?.error && (
        <p className="mt-1 font-mono text-xs text-danger">{snap.error}</p>
      )}
    </div>
  );
}
