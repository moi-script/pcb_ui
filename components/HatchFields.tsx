"use client";

type Props = {
  spacing: number;
  setSpacing: (v: number) => void;
  angle: number;
  setAngle: (v: number) => void;
  cross: boolean;
  setCross: (v: boolean) => void;
  disabled?: boolean;
};

/**
 * The fill-only controls, shared by the uploader and the re-trace panel.
 *
 * Spacing is the one that decides whether the resist actually works: lines
 * further apart than the pen is wide leave bare copper between them, and the
 * etch finds it.
 */
export default function HatchFields({
  spacing,
  setSpacing,
  angle,
  setAngle,
  cross,
  setCross,
  disabled = false,
}: Props) {
  return (
    <div className="mt-3 rounded border border-line bg-well/40 p-3">
      <span className="tlabel">fill</span>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="tlabel">line spacing (mm)</span>
          <input
            type="number"
            min={0.05}
            max={5}
            step={0.05}
            value={spacing}
            disabled={disabled}
            onChange={(e) => setSpacing(Number(e.target.value))}
            className="field mt-1 w-full"
          />
        </label>
        <label className="block">
          <span className="tlabel">angle</span>
          <select
            value={angle}
            disabled={disabled}
            onChange={(e) => setAngle(Number(e.target.value))}
            className="field mt-1 w-full"
          >
            <option value={45}>45°</option>
            <option value={0}>0° — horizontal</option>
            <option value={90}>90° — vertical</option>
            <option value={135}>135°</option>
          </select>
        </label>
      </div>

      <label className="mt-3 flex items-center gap-2 text-sm text-ink-soft">
        <input
          type="checkbox"
          checked={cross}
          disabled={disabled}
          onChange={(e) => setCross(e.target.checked)}
        />
        Cross-hatch (second pass at 90°)
      </label>

      <p className="mt-3 text-xs text-muted">
        Set the spacing to your pen&apos;s width or a little under. Wider and
        the etch gets in between the lines. Cross-hatching doubles the plotting
        time and covers far more reliably.
      </p>
    </div>
  );
}
