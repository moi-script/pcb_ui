"use client";

import { useEffect, useState } from "react";
import {
  api,
  type DropHistory as History,
  type DropKind,
  type DropReport as Report,
} from "@/lib/api";

// One colour per axis, used for the axis word in every line shown, so a
// glance down the listing says what each line moves: X and Y are the
// steppers, Z is the pen servo.
const AXIS_COLOR: Record<string, string> = {
  X: "text-copper",
  Y: "text-signal",
  Z: "text-warn",
};

const KIND_SHORT: Record<DropKind, string> = {
  z_down: "Z pen down",
  z_up: "Z pen up",
  draw: "XY drawing",
  travel: "XY travel",
  idle: "not moving",
  unknown: "unknown",
};

const ROLE_NOTE: Record<Report["context"][number]["role"], string> = {
  before: "",
  match: "← pen was here",
  candidate: "also passes here",
  queued: "queued, never ran",
  unsent: "never sent",
};

/**
 * A G-code line with its moving axis words coloured and everything else
 * dimmed. An axis word the line names but does not change (a travel to where
 * the pen already is) stays dim: it is the change that moves a motor.
 */
function Code({ code, axes }: { code: string; axes: string }) {
  const parts = code.split(/(\s+)/);
  return (
    <>
      {parts.map((part, i) => {
        const letter = part[0]?.toUpperCase() ?? "";
        const moving = axes.includes(letter) && /^[XYZ][-+.\d]/i.test(part);
        return (
          <span
            key={i}
            className={moving ? `font-semibold ${AXIS_COLOR[letter]}` : "text-muted"}
          >
            {part}
          </span>
        );
      })}
    </>
  );
}

function when(at: number): string {
  return new Date(at * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Everything known about one drop: what, where, and what it points to. */
export function DropCard({ report }: { report: Report }) {
  const pos = report.pos;
  return (
    <div className="mt-3 rounded-sm border border-danger/40 bg-danger/5 p-3">
      <p className="text-sm font-semibold text-danger">{report.headline}</p>
      <p className="mt-1.5 text-sm text-ink-soft">{report.explanation}</p>

      {report.axes && (
        <p className="mt-2 font-mono text-xs text-muted">
          moving:{" "}
          {report.axes.split("").map((a) => (
            <span key={a} className={`mr-1.5 font-semibold ${AXIS_COLOR[a]}`}>
              {a === "Z" ? "Z (pen servo)" : a}
            </span>
          ))}
          {report.confidence === "likely" && (
            <span className="text-faint">
              · likely — lines {report.candidates.join(", ")} all pass this point
            </span>
          )}
        </p>
      )}

      <ol className="mt-2 overflow-x-auto rounded-sm bg-well py-1 font-mono text-xs">
        {report.context.map((c) => (
          <li
            key={c.n}
            className={`flex gap-3 whitespace-nowrap px-2 py-0.5 ${
              c.role === "match"
                ? "border-l-2 border-danger bg-danger/10"
                : c.role === "queued" || c.role === "unsent"
                ? "border-l-2 border-transparent opacity-50"
                : "border-l-2 border-transparent"
            }`}
          >
            <span className="w-12 shrink-0 text-right text-faint">{c.n}</span>
            <span>
              <Code code={c.code} axes={c.axes} />
            </span>
            {ROLE_NOTE[c.role] && (
              <span className={c.role === "match" ? "text-danger" : "text-faint"}>
                {ROLE_NOTE[c.role]}
              </span>
            )}
          </li>
        ))}
      </ol>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[0.7rem] text-muted">
        <div>
          last position{" "}
          <span className="text-ink-soft">
            {pos
              ? `X${pos[0].toFixed(2)} Y${pos[1].toFixed(2)} Z${pos[2].toFixed(2)}`
              : "none received"}
          </span>
        </div>
        <div>
          reported{" "}
          <span className="text-ink-soft">
            {report.statusAge == null ? "—" : `${report.statusAge.toFixed(2)} s before`}
          </span>{" "}
          · {report.state || "?"}
        </div>
        <div>
          accepted{" "}
          <span className="text-ink-soft">
            {report.acked}/{report.total}
          </span>{" "}
          · sent {report.sent}
        </div>
        <div className="truncate" title={report.reason}>
          {report.cause === "controller_reset" ? "restart" : "error"}{" "}
          <span className="text-ink-soft">{report.reason}</span>
        </div>
      </dl>
    </div>
  );
}

/**
 * Past drops, counted by what the machine was doing. One report says what
 * one drop was doing; the tally is what finds the cause — drops that pile up
 * on Z are the servo's power, not the G-code.
 *
 * `refresh` changes whenever a new drop may have been recorded, so the
 * strip reloads without polling.
 */
export function DropHistoryStrip({ refresh }: { refresh: unknown }) {
  const [history, setHistory] = useState<History | null>(null);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .drops()
      .then((h) => alive && setHistory(h))
      .catch(() => alive && setHistory(null));
    return () => {
      alive = false;
    };
  }, [refresh]);

  if (!history || history.reports.length === 0) return null;

  const counts = (Object.keys(KIND_SHORT) as DropKind[]).filter(
    (k) => history.tally[k] > 0
  );
  // The kind that leads outright, and only once there are two of it: a
  // single drop, or a tie, is not a pattern and should not be painted as one.
  const sorted = [...counts].sort((a, b) => history.tally[b] - history.tally[a]);
  const top =
    sorted.length &&
    history.tally[sorted[0]] >= 2 &&
    history.tally[sorted[0]] > (history.tally[sorted[1]] ?? 0)
      ? sorted[0]
      : null;

  return (
    <div className="mt-3 border-t border-line pt-2">
      <button
        className="flex w-full items-center justify-between font-mono text-xs text-muted hover:text-ink-soft"
        onClick={() => setOpen((o) => !o)}
      >
        <span>
          drop history ({history.reports.length}) ·{" "}
          {counts.map((k) => (
            <span key={k} className={k === top ? "text-danger" : ""}>
              {KIND_SHORT[k]} {history.tally[k]}
              {"  "}
            </span>
          ))}
        </span>
        <span>{open ? "hide" : "show"}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-1">
          {history.reports.map((r, i) => (
            <div key={`${r.at}-${i}`}>
              <button
                className="w-full truncate text-left font-mono text-xs text-ink-soft hover:text-copper"
                onClick={() => setPicked(picked === i ? null : i)}
              >
                <span className="text-faint">{when(r.at)}</span> · {r.job} ·{" "}
                {KIND_SHORT[r.kind]}
                {r.line != null && (
                  <>
                    {" "}
                    · line {r.line}{" "}
                    <Code code={r.code} axes={r.axes} />
                  </>
                )}
              </button>
              {picked === i && <DropCard report={r} />}
            </div>
          ))}
          <button
            className="mt-1 font-mono text-[0.7rem] text-faint hover:text-danger"
            onClick={() =>
              api.clearDrops().then(() => {
                setHistory(null);
                setOpen(false);
              })
            }
          >
            clear history
          </button>
        </div>
      )}
    </div>
  );
}
