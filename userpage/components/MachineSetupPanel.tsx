"use client";

import { useEffect, useState } from "react";

import { api, type MachineSetup, type Origin } from "@/lib/api";

const CORNERS: { value: Origin; label: string }[] = [
  { value: "top-left", label: "top-left" },
  { value: "top-right", label: "top-right" },
  { value: "bottom-left", label: "bottom-left" },
  { value: "bottom-right", label: "bottom-right" },
];

/**
 * Bed size, start corner and reversed axes — the machine setup Universal
 * G-code Sender offers. grbl_servo_z ignores Grbl's `$3`, so reversal is done
 * by the server on every line it sends and every position it reads back.
 */
export default function MachineSetupPanel({
  setup,
  disabled,
}: {
  setup: MachineSetup | undefined;
  disabled: boolean;
}) {
  const [draft, setDraft] = useState<MachineSetup | null>(setup ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Follow the server until the operator starts editing.
  const key = setup ? JSON.stringify(setup) : "";
  const [baseline, setBaseline] = useState(key);
  useEffect(() => {
    if (key && key !== baseline) {
      setDraft(setup ?? null);
      setBaseline(key);
    }
  }, [key, baseline, setup]);

  if (!draft) return null;
  const max = draft.maxTravel;
  const dirty = JSON.stringify(draft) !== key;

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const next = await api.saveMachineSetup({
        travel_x: draft.travelX,
        travel_y: draft.travelY,
        origin: draft.origin,
        invert_x: draft.invertX,
        invert_y: draft.invertY,
      });
      setDraft(next);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const size = (axis: "travelX" | "travelY", label: string) => (
    <label className="block">
      <span className="tlabel">{label} (mm)</span>
      <input
        type="number"
        min={1}
        max={max}
        step={1}
        className="field mt-1"
        value={draft[axis]}
        disabled={disabled}
        onChange={(e) =>
          setDraft({ ...draft, [axis]: Number(e.target.value) })
        }
      />
    </label>
  );

  return (
    <div className="panel p-5">
      <span className="tlabel">Machine setup</span>
      <p className="mt-2 text-xs text-muted">
        The bed is at most {max} x {max} mm. The start corner is the corner of
        the drawing that sits under the pen when you connect or zero. Reverse
        an axis if a jog moves the pen the wrong way.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3">
        {size("travelX", "Bed width X")}
        {size("travelY", "Bed height Y")}
      </div>

      <label className="tlabel mt-4 block">Start corner</label>
      <div className="mt-1 grid grid-cols-2 gap-1.5">
        {CORNERS.map((c) => (
          <button
            key={c.value}
            type="button"
            disabled={disabled}
            className={`btn font-mono text-xs ${
              draft.origin === c.value ? "btn-copper" : "btn-ghost"
            }`}
            onClick={() => setDraft({ ...draft, origin: c.value })}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-sm">
        {(["invertX", "invertY"] as const).map((axis) => (
          <label key={axis} className="flex items-center gap-2">
            <input
              type="checkbox"
              className="accent-copper"
              checked={draft[axis]}
              disabled={disabled}
              onChange={(e) => setDraft({ ...draft, [axis]: e.target.checked })}
            />
            reverse {axis === "invertX" ? "X" : "Y"}
          </label>
        ))}
      </div>

      {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      {saved && !dirty && !error && (
        <p className="mt-3 font-mono text-xs text-signal">saved</p>
      )}

      <button
        className="btn btn-copper mt-4 w-full"
        disabled={disabled || busy || !dirty}
        title={disabled ? "Stop the plot before changing the setup" : undefined}
        onClick={() => void save()}
      >
        {busy ? "saving…" : "Save setup"}
      </button>
    </div>
  );
}
