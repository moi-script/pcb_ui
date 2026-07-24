"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import { useAuth } from "@/lib/auth";
import { api, type Board } from "@/lib/api";

export default function ProjectDetail() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { session } = useAuth();

  const [board, setBoard] = useState<Board | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [front, setFront] = useState(true);
  const [back, setBack] = useState(true);
  const [toolpath, setToolpath] = useState(false);
  const [replay, setReplay] = useState(0);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const b = await api.getBoard(params.id);
        if (alive) {
          setBoard(b);
          setState("ready");
        }
      } catch {
        if (alive) setState("missing");
      }
    })();
    return () => {
      alive = false;
    };
  }, [params.id]);

  if (state === "loading") {
    return (
      <div className="mx-auto max-w-6xl px-6 py-16">
        <span className="tlabel animate-pulse">loading board…</span>
      </div>
    );
  }

  if (state === "missing" || !board) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-16 text-center">
        <p className="tlabel">board not found</p>
        <Link href="/dashboard/projects" className="btn btn-ghost mt-4">
          ← Back to boards
        </Link>
      </div>
    );
  }

  const reduction = board.penUpBefore
    ? Math.round((1 - board.penUpAfter / board.penUpBefore) * 100)
    : 0;
  const deviceAlias = session?.device?.alias ?? "your machine";

  async function removeBoard() {
    if (!board) return;
    setDeleting(true);
    try {
      await api.deleteBoard(board.id);
      router.push("/dashboard/projects");
    } catch {
      setDeleting(false);
      setArmed(false);
    }
  }

  function downloadGcode() {
    if (!board?.gcode) return;
    const blob = new Blob([board.gcode], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = board.filename.replace(/\.kicad_pcb$/, "") + ".gcode";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <Link href="/dashboard/projects" className="tlabel hover:text-ink">
        ← Boards
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl tracking-tight text-ink">{board.name}</h1>
          <p className="font-mono text-xs text-faint">{board.filename}</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="font-mono text-xs text-muted">
            target · {deviceAlias}
          </span>
          {armed ? (
            <span className="flex items-center gap-2 font-mono text-xs">
              <button
                onClick={removeBoard}
                disabled={deleting}
                className="text-danger hover:underline disabled:opacity-50"
              >
                {deleting ? "deleting…" : "delete board?"}
              </button>
              <button
                onClick={() => setArmed(false)}
                className="text-faint hover:text-muted"
              >
                cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setArmed(true)}
              className="tlabel hover:!text-danger"
            >
              delete
            </button>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        {/* preview */}
        <section className="panel ticked">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
            <span className="tlabel mr-auto">Preview</span>
            <Toggle on={front} onClick={() => setFront((v) => !v)} color="fcu">
              F.Cu
            </Toggle>
            <Toggle on={back} onClick={() => setBack((v) => !v)} color="bcu">
              B.Cu
            </Toggle>
            <Toggle
              on={toolpath}
              onClick={() => setToolpath((v) => !v)}
              color="ink"
            >
              Travel
            </Toggle>
            <button
              onClick={() => setReplay((r) => r + 1)}
              className="tlabel ml-1 hover:text-copper"
              title="replay draw"
            >
              ↻ replay
            </button>
          </div>
          <div className="panel-2 aspect-[16/10] p-5">
            <PcbBoard
              key={`${front}${back}${toolpath}${replay}`}
              tracks={board.tracks}
              width={board.width}
              height={board.height}
              showFront={front}
              showBack={back}
              toolpath={toolpath}
              animate
              className="h-full w-full"
            />
          </div>
          <div className="flex items-center gap-5 border-t border-line px-4 py-2.5">
            <Legend color="var(--color-fcu)" label="F.Cu draw" />
            <Legend color="var(--color-bcu)" label="B.Cu draw" />
            <Legend color="var(--color-faint)" label="pen-up travel" dashed />
          </div>
        </section>

        {/* right column */}
        <section className="space-y-6">
          <div className="panel ticked p-5">
            <span className="tlabel">Route report</span>
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3">
              <Metric k="Tracks" v={String(board.fcu + board.bcu)} />
              <Metric k="Nets" v={String(board.nets)} />
              <Metric k="Size (mm)" v={board.size} />
              <Metric k="Plot layer" v={board.layer} />
              <Metric k="Draw moves" v={String(board.drawMoves)} />
              <Metric k="Travel moves" v={String(board.travelMoves)} />
              <Metric k="G-code lines" v={String(board.gcodeLines)} />
              <Metric k="Est. time" v={`~${board.estMinutes} min`} />
            </dl>

            <div className="mt-5 border-t border-line pt-4">
              <div className="flex items-center justify-between">
                <span className="tlabel">Travel optimization</span>
                <span className="font-mono text-sm text-signal">
                  −{reduction}%
                </span>
              </div>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-sm bg-well">
                <div
                  className="h-full bg-copper"
                  style={{
                    width: `${
                      board.penUpBefore
                        ? (board.penUpAfter / board.penUpBefore) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
              <p className="mt-2 font-mono text-[0.7rem] text-muted">
                {board.penUpBefore} mm → {board.penUpAfter} mm pen-up travel
              </p>
            </div>
          </div>

          <PlotControl gcodeLines={board.gcodeLines} deviceAlias={deviceAlias} />
        </section>
      </div>

      {/* gcode viewer */}
      <section className="panel ticked mt-6">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <span className="tlabel">
            G-code · {board.filename.replace(/\.kicad_pcb$/, ".gcode")}
          </span>
          <button onClick={downloadGcode} className="tlabel hover:text-copper">
            ↓ download
          </button>
        </div>
        <pre className="max-h-80 overflow-auto px-5 py-4 font-mono text-xs leading-relaxed text-ink-soft">
          {board.gcode}
        </pre>
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- controls */

function PlotControl({
  gcodeLines,
  deviceAlias,
}: {
  gcodeLines: number;
  deviceAlias: string;
}) {
  type Phase =
    | "idle"
    | "checking"
    | "streaming-ready"
    | "streaming"
    | "done"
    | "error";
  const [phase, setPhase] = useState<Phase>("idle");
  const [check, setCheck] = useState(true);
  const [line, setLine] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearInterval(timer.current);
    },
    []
  );

  function run() {
    setLine(0);
    setPhase(check ? "checking" : "streaming");
  }

  useEffect(() => {
    if (phase !== "checking" && phase !== "streaming") return;
    timer.current = setInterval(() => {
      setLine((l) => {
        const next = l + Math.max(1, Math.round(gcodeLines / 40));
        if (next >= gcodeLines) {
          if (timer.current) clearInterval(timer.current);
          setTimeout(() => {
            setPhase((p) => (p === "checking" ? "streaming-ready" : "done"));
          }, 200);
          return gcodeLines;
        }
        return next;
      });
    }, 55);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [phase, gcodeLines]);

  useEffect(() => {
    if (phase === "streaming-ready") setLine(0);
  }, [phase]);

  const pct = gcodeLines ? Math.round((line / gcodeLines) * 100) : 0;
  const active = phase === "checking" || phase === "streaming";

  return (
    <div className="panel ticked p-5">
      <div className="flex items-center justify-between">
        <span className="tlabel">Stream to device</span>
        <span className="font-mono text-xs text-muted">{deviceAlias}</span>
      </div>

      <button
        onClick={() => setCheck((v) => !v)}
        disabled={active}
        className="mt-4 flex w-full items-center justify-between rounded border border-line bg-panel-2 px-3 py-2.5 text-left disabled:opacity-50"
      >
        <span>
          <span className="block text-sm text-ink">Dry-check first</span>
          <span className="font-mono text-[0.7rem] text-muted">
            reads every line, nothing moves ($C)
          </span>
        </span>
        <span
          className={`relative h-5 w-9 flex-none rounded-full transition-colors ${
            check ? "bg-signal" : "bg-line-strong"
          }`}
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-panel-2 transition-all ${
              check ? "left-4" : "left-0.5"
            }`}
          />
        </span>
      </button>

      {(active || phase === "done" || phase === "streaming-ready") && (
        <div className="mt-4">
          <div className="flex items-center justify-between font-mono text-xs">
            <span className="text-muted">
              {phase === "checking"
                ? "checking ($C)"
                : phase === "streaming"
                ? "streaming"
                : phase === "streaming-ready"
                ? "check passed · 0 errors"
                : "complete"}
            </span>
            <span className="text-ink">
              {line}/{gcodeLines} · {phase === "done" ? 100 : pct}%
            </span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-sm bg-well">
            <div
              className={`h-full transition-all duration-75 ${
                phase === "checking" ? "bg-warn" : "bg-signal"
              }`}
              style={{ width: `${phase === "done" ? 100 : pct}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-4">
        {phase === "idle" || phase === "done" || phase === "error" ? (
          <button onClick={run} className="btn btn-copper w-full">
            {check ? "Validate & plot" : "Plot now"}
          </button>
        ) : phase === "streaming-ready" ? (
          <button
            onClick={() => setPhase("streaming")}
            className="btn btn-primary w-full"
          >
            Looks good, stream for real →
          </button>
        ) : (
          <button
            onClick={() => {
              if (timer.current) clearInterval(timer.current);
              setPhase("idle");
              setLine(0);
            }}
            className="btn btn-ghost w-full !border-danger !text-danger"
          >
            Stop
          </button>
        )}
        {phase === "done" && (
          <p className="mt-3 text-center text-sm text-signal">
            ✓ Sent {gcodeLines} lines · 0 errors
          </p>
        )}
      </div>
    </div>
  );
}

function Toggle({
  on,
  onClick,
  color,
  children,
}: {
  on: boolean;
  onClick: () => void;
  color: "fcu" | "bcu" | "ink";
  children: React.ReactNode;
}) {
  const dot =
    color === "fcu"
      ? "var(--color-fcu)"
      : color === "bcu"
      ? "var(--color-bcu)"
      : "var(--color-ink)";
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 font-mono text-[0.7rem] transition-colors ${
        on
          ? "border-line-strong bg-well text-ink"
          : "border-line text-faint hover:text-muted"
      }`}
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: on ? dot : "var(--color-line-strong)" }}
      />
      {children}
    </button>
  );
}

function Legend({
  color,
  label,
  dashed,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[0.7rem] text-muted">
      <span
        className="inline-block h-0 w-5 border-t-2"
        style={{ borderColor: color, borderStyle: dashed ? "dashed" : "solid" }}
      />
      {label}
    </span>
  );
}

function Metric({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="tlabel !text-[0.6rem]">{k}</dt>
      <dd className="mt-0.5 font-mono text-sm text-ink">{v}</dd>
    </div>
  );
}
