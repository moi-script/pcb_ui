"use client";

import { useState } from "react";

const STEPS = [0.1, 1, 10];

/**
 * Manual moves.
 *
 * Z lives in its own column rather than in the XY cross: the cross is a map
 * of the table seen from above, and a pen axis dropped into the middle of it
 * is a button someone presses expecting the carriage to move sideways.
 */
export default function JogPad({
  disabled,
  onJog,
}: {
  disabled: boolean;
  onJog: (axis: string, distance: number) => void;
}) {
  const [step, setStep] = useState(1);

  function keys(e: React.KeyboardEvent) {
    // Only while the pad itself has focus. A page-wide arrow-key listener
    // moves a machine when the user is only trying to scroll.
    if (disabled) return;
    const map: Record<string, [string, number]> = {
      ArrowRight: ["X", step],
      ArrowLeft: ["X", -step],
      ArrowUp: ["Y", step],
      ArrowDown: ["Y", -step],
      PageUp: ["Z", step],
      PageDown: ["Z", -step],
    };
    const hit = map[e.key];
    if (!hit) return;
    e.preventDefault();
    onJog(hit[0], hit[1]);
  }

  const btn =
    "btn btn-ghost h-11 w-full font-mono text-sm disabled:opacity-40";

  return (
    <div
      className="panel ticked p-5 outline-none focus:border-copper"
      tabIndex={0}
      onKeyDown={keys}
      aria-label="Jog pad — arrow keys move X and Y, PageUp/PageDown move Z"
    >
      <div className="flex items-center justify-between">
        <span className="tlabel">Jog</span>
        <div className="flex gap-px bg-line">
          {STEPS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStep(s)}
              className={`px-2.5 py-1 font-mono text-xs ${
                step === s ? "bg-copper text-paper" : "bg-panel text-muted"
              }`}
            >
              {s}
            </button>
          ))}
          <span className="bg-panel px-2 py-1 font-mono text-xs text-faint">
            mm
          </span>
        </div>
      </div>

      <div className="mt-4 flex gap-5">
        {/* XY, laid out as the table looks from above */}
        <div className="grid flex-1 grid-cols-3 gap-1.5">
          <span />
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("Y", step)}
          >
            Y+
          </button>
          <span />
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("X", -step)}
          >
            X−
          </button>
          <span className="flex items-center justify-center font-mono text-[0.7rem] text-faint">
            {step}
          </span>
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("X", step)}
          >
            X+
          </button>
          <span />
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("Y", -step)}
          >
            Y−
          </button>
          <span />
        </div>

        {/* Z — the pen axis, deliberately apart */}
        <div className="flex w-20 flex-col gap-1.5">
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("Z", step)}
          >
            Z+
          </button>
          <span className="flex-1" />
          <button
            className={btn}
            disabled={disabled}
            onClick={() => onJog("Z", -step)}
          >
            Z−
          </button>
        </div>
      </div>
    </div>
  );
}
