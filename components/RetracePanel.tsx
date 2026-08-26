"use client";

import { useState } from "react";
import { api, type Board, type TraceMode, type TraceParams } from "@/lib/api";
import HatchFields from "@/components/HatchFields";

type Props = {
  board: Board;
  /** hand back the re-traced board so the preview and report update */
  onDone: (b: Board) => void;
};

/**
 * Tune a traced board without re-uploading the image.
 *
 * Threshold and size are guesses until you see the result, so this exists to
 * make the second and third attempt cheap. The server keeps the source image
 * and re-traces in place, which is why the board's id and name survive.
 */
export default function RetracePanel({ board, onDone }: Props) {
  const p = board.traceParams;

  const [sizeMm, setSizeMm] = useState(p?.size_mm ?? 50);
  const [mode, setMode] = useState<TraceMode>(p?.mode ?? "centerline");
  const [preset, setPreset] = useState<TraceParams["preset"]>(p?.preset ?? "line");
  const [invert, setInvert] = useState(p?.invert ?? false);
  const [autoCut, setAutoCut] = useState((p?.threshold ?? null) === null);
  const [threshold, setThreshold] = useState(p?.threshold ?? 128);
  const [hatchSpacing, setHatchSpacing] = useState(p?.hatch_spacing_mm ?? 0.4);
  const [hatchAngle, setHatchAngle] = useState(p?.hatch_angle ?? 45);
  const [hatchCross, setHatchCross] = useState(p?.hatch_cross ?? false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.retrace(board.id, {
        size_mm: sizeMm,
        mode,
        preset,
        threshold: autoCut ? null : threshold,
        invert,
        hatch_spacing_mm: hatchSpacing,
        hatch_angle: hatchAngle,
        hatch_cross: hatchCross,
      });
      onDone(next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!board.hasSource) {
    return (
      <div className="panel ticked p-5">
        <span className="tlabel">Re-trace</span>
        <p className="mt-2 text-xs text-muted">
          This board was traced before source images were kept, so there is
          nothing to re-trace. Upload the image again to tune it.
        </p>
      </div>
    );
  }

  return (
    <div className="panel ticked p-5">
      <span className="tlabel">Re-trace</span>
      <p className="mt-1 text-xs text-muted">
        Adjust and run again. The board keeps its name and link.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="tlabel">longest edge (mm)</span>
          <input
            type="number"
            min={1}
            max={300}
            value={sizeMm}
            disabled={busy}
            onChange={(e) => setSizeMm(Number(e.target.value))}
            className="field mt-1 w-full"
          />
        </label>
        <label className="block">
          <span className="tlabel">source</span>
          <select
            value={preset}
            disabled={busy}
            onChange={(e) => setPreset(e.target.value as TraceParams["preset"])}
            className="field mt-1 w-full"
          >
            <option value="line">Line art</option>
            <option value="pcb">PCB photo</option>
          </select>
        </label>
      </div>

      <div className="mt-3">
        <span className="tlabel">trace mode</span>
        <select
          value={mode}
          disabled={busy}
          onChange={(e) => setMode(e.target.value as TraceMode)}
          className="field mt-1 w-full"
        >
          <option value="centerline">Centreline — down the middle</option>
          <option value="outline">Outline — around each shape</option>
          <option value="fill">Fill — covers copper for etch resist</option>
        </select>
        {mode === "fill" && (
          <HatchFields
            spacing={hatchSpacing}
            setSpacing={setHatchSpacing}
            angle={hatchAngle}
            setAngle={setHatchAngle}
            cross={hatchCross}
            setCross={setHatchCross}
            disabled={busy}
          />
        )}
      </div>

      <div className="mt-4 border-t border-line pt-4">
        <div className="flex items-center justify-between">
          <span className="tlabel">ink threshold</span>
          <label className="flex items-center gap-2 text-xs text-ink-soft">
            <input
              type="checkbox"
              checked={autoCut}
              disabled={busy}
              onChange={(e) => setAutoCut(e.target.checked)}
            />
            auto
          </label>
        </div>
        {autoCut ? (
          <p className="mt-2 text-xs text-muted">
            Picked from the image, then softened so faint linework is not lost.
          </p>
        ) : (
          <>
            <input
              type="range"
              min={1}
              max={254}
              value={threshold}
              disabled={busy}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="mt-2 w-full accent-[var(--color-copper)]"
            />
            <div className="flex items-center justify-between font-mono text-xs text-muted">
              <span>less ink</span>
              <span className="text-copper">{threshold}</span>
              <span>more ink</span>
            </div>
          </>
        )}
      </div>

      <label className="mt-4 flex items-center gap-2 text-sm text-ink-soft">
        <input
          type="checkbox"
          checked={invert}
          disabled={busy}
          onChange={(e) => setInvert(e.target.checked)}
        />
        Light lines on dark
      </label>

      {error && <p className="mt-3 text-sm text-danger">{error}</p>}

      <button
        type="button"
        onClick={run}
        disabled={busy}
        className="btn btn-copper mt-4 w-full"
      >
        {busy ? "Re-tracing…" : "Re-trace"}
      </button>
    </div>
  );
}
