"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import InlineEdit from "@/components/InlineEdit";
import RetracePanel from "@/components/RetracePanel";
import { useAuth } from "@/lib/auth";
import { api, type Board } from "@/lib/api";
import { useMachine } from "@/lib/machine";

// Three.js is ~600 KB and needs a DOM, so it loads on this page only, client-side.
const GcodeVisualizer = dynamic(() => import("@/components/GcodeVisualizer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[26rem] items-center justify-center font-mono text-xs text-faint">
      loading visualizer…
    </div>
  ),
});

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
  // A traced image is one layer with one synthetic net, so the copper-layer
  // controls and counts would all be dead weight on it.
  const traced = board.source === "image";

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
          <h1 className="text-2xl tracking-tight text-ink">
            <InlineEdit
              value={board.name}
              ariaLabel="Rename board"
              onSave={async (next) => {
                const updated = await api.renameBoard(board.id, next);
                setBoard((b) => (b ? { ...b, name: updated.name } : b));
              }}
            />
          </h1>
          <p className="font-mono text-xs text-faint">{board.filename}</p>
        </div>
        <div className="flex items-center gap-4">
          <MachineTag />
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
            {!traced && (
              <>
                <Toggle
                  on={front}
                  onClick={() => setFront((v) => !v)}
                  color="fcu"
                >
                  F.Cu
                </Toggle>
                <Toggle
                  on={back}
                  onClick={() => setBack((v) => !v)}
                  color="bcu"
                >
                  B.Cu
                </Toggle>
              </>
            )}
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
              strokes={board.strokes}
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
            {traced ? (
              <Legend
                color="var(--color-fcu)"
                label={
                  board.traceParams?.mode === "fill"
                    ? "hatch fill"
                    : board.traceParams?.mode === "outline"
                      ? "traced outline"
                      : "traced centreline"
                }
              />
            ) : (
              <>
                <Legend color="var(--color-fcu)" label="F.Cu draw" />
                <Legend color="var(--color-bcu)" label="B.Cu draw" />
              </>
            )}
            <Legend color="var(--color-faint)" label="pen-up travel" dashed />
          </div>
        </section>

        {/* right column */}
        <section className="space-y-6">
          <div className="panel ticked p-5">
            <span className="tlabel">
              {traced ? "Trace report" : "Route report"}
            </span>
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3">
              {traced ? (
                <>
                  <Metric k="Strokes" v={String(board.fcu)} />
                  <Metric k="Trace mode" v={board.traceParams?.mode ?? "—"} />
                </>
              ) : (
                <>
                  <Metric k="Tracks" v={String(board.fcu + board.bcu)} />
                  <Metric k="Nets" v={String(board.nets)} />
                </>
              )}
              <Metric k="Size (mm)" v={board.size} />
              {!traced && <Metric k="Plot layer" v={board.layer} />}
              {traced && (
                <Metric k="Source" v={board.traceParams?.preset ?? "—"} />
              )}
              {traced && board.traceParams?.mode === "fill" && (
                <Metric
                  k="Fill spacing"
                  v={`${board.traceParams.hatch_spacing_mm ?? 0.4} mm${
                    board.traceParams.hatch_cross ? " ×2" : ""
                  }`}
                />
              )}
              <Metric k="Draw moves" v={String(board.drawMoves)} />
              <Metric k="Travel moves" v={String(board.travelMoves)} />
              <Metric k="G-code lines" v={String(board.gcodeLines)} />
              <Metric k="Est. time" v={`~${board.estMinutes} min`} />
            </dl>

            {traced && !!board.traceInfo?.warnings.length && (
              <ul className="mt-4 space-y-1 border-t border-line pt-4 text-xs text-warn">
                {board.traceInfo.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

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

          {traced && (
            <RetracePanel
              board={board}
              onDone={(b) => {
                setBoard(b);
                setReplay((r) => r + 1); // redraw the preview animation
              }}
            />
          )}

          <PlotControl
            boardId={board.id}
            boardName={board.name}
            gcodeLines={board.gcodeLines}
          />
        </section>
      </div>

      {/* toolpath simulation — reads the real G-code, not the stored geometry */}
      {board.gcode && (
        <section className="panel ticked mt-6">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="tlabel">Toolpath simulation</span>
            <span className="font-mono text-xs text-faint">
              what the machine will actually run
            </span>
          </div>
          <LiveVisualizer gcode={board.gcode} boardName={board.name} />
        </section>
      )}

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

/** The machine this board would go to, in the page header. */
function MachineTag() {
  const { snap, connected } = useMachine();
  return (
    <span className="font-mono text-xs text-muted">
      target{" "}
      {connected ? (
        <span className="text-ink">{snap?.conn.port}</span>
      ) : (
        <Link href="/connect" className="text-copper hover:underline">
          no machine
        </Link>
      )}
    </span>
  );
}

/**
 * The toolpath view, wired to the running job.
 *
 * liveIndex and penPos are handed over only while THIS board's job is
 * running. A job for a different board would otherwise draw its progress
 * onto this one's toolpath.
 */
function LiveVisualizer({
  gcode,
  boardName,
}: {
  gcode: string;
  boardName: string;
}) {
  const { snap } = useMachine();
  const job = snap?.job ?? null;
  const active = job?.state === "running" || job?.state === "paused";
  const mine = active && job?.name === boardName;

  return (
    <GcodeVisualizer
      gcode={gcode}
      liveIndex={mine && job ? job.acked : null}
      penPos={mine && snap ? snap.wpos : null}
    />
  );
}

function PlotControl({
  boardId,
  boardName,
  gcodeLines,
}: {
  boardId: string;
  boardName: string;
  gcodeLines: number;
}) {
  const { snap, connected, live } = useMachine();
  const [check, setCheck] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // Job state comes from the machine, not from local state. A job started in
  // another tab, or before this page was opened, is still this machine's
  // job, and two tabs tracking it separately would disagree about whether
  // the machine is busy.
  const job = snap?.job ?? null;
  const running = job?.state === "running";
  const paused = job?.state === "paused";
  const active = running || paused;
  const mine = job?.name === boardName;
  const reportable = Boolean(job && mine && job.state !== "idle");

  const total = job?.total || gcodeLines;
  const acked = job?.acked ?? 0;
  const pct = total ? Math.round((acked / total) * 100) : 0;

  async function guard(fn: () => Promise<unknown>) {
    setErr("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!connected) {
    return (
      <div className="panel ticked p-5">
        <span className="tlabel">Plot this board</span>
        <p className="mt-3 text-sm text-muted">
          {live
            ? "No machine connected. Plug the controller into this PC over USB and pick its port."
            : "Not talking to the server. Is the API running on port 8000?"}
        </p>
        <Link href="/connect" className="btn btn-copper mt-4 w-full">
          Connect a machine
        </Link>
      </div>
    );
  }

  return (
    <div className="panel ticked p-5">
      <div className="flex items-center justify-between">
        <span className="tlabel">Plot this board</span>
        <span className="font-mono text-xs text-muted">
          {snap?.conn.port} · {snap?.state}
        </span>
      </div>

      {!active && (
        <button
          onClick={() => setCheck((v) => !v)}
          disabled={busy}
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
      )}

      {reportable && job && (
        <div className="mt-4">
          <div className="flex items-center justify-between font-mono text-xs">
            <span className="text-muted">
              {running
                ? job.check
                  ? "checking ($C)"
                  : "lines sent"
                : paused
                ? "paused"
                : job.state === "done"
                ? job.check
                  ? "check passed · 0 errors"
                  : "finished"
                : job.state === "stopped"
                ? "stopped"
                : "failed"}
            </span>
            <span className="text-ink">
              {acked}/{total} · {pct}%
            </span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-sm bg-well">
            <div
              className={`h-full transition-all duration-100 ${
                job.state === "error"
                  ? "bg-danger"
                  : job.check
                  ? "bg-warn"
                  : "bg-signal"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          {/* "Sent", not "complete". GRBL acknowledges a line when it has
              parsed and queued it, so the pen is still behind this number:
              a bar claiming completion would finish before the machine did. */}
          <p className="mt-1.5 font-mono text-[0.7rem] text-faint">
            lines the controller has accepted; the pen is a little behind
          </p>
        </div>
      )}

      <div className="mt-4">
        {running ? (
          <div className="flex gap-1.5">
            <button
              className="btn btn-ghost flex-1"
              disabled={busy}
              onClick={() => guard(() => api.pauseJob())}
            >
              Pause
            </button>
            <button
              className="btn btn-ghost flex-1 !border-danger !text-danger"
              disabled={busy}
              onClick={() => guard(() => api.stopJob())}
            >
              Stop
            </button>
          </div>
        ) : paused ? (
          <div className="flex gap-1.5">
            <button
              className="btn btn-copper flex-1"
              disabled={busy}
              onClick={() => guard(() => api.resumeJob())}
            >
              Resume
            </button>
            <button
              className="btn btn-ghost flex-1 !border-danger !text-danger"
              disabled={busy}
              onClick={() => guard(() => api.stopJob())}
            >
              Stop
            </button>
          </div>
        ) : (
          <button
            onClick={() => guard(() => api.run(boardId, check))}
            disabled={busy}
            className="btn btn-copper w-full"
          >
            {busy
              ? "sending…"
              : check
              ? "Validate & plot"
              : reportable
              ? "Plot again"
              : "Plot now"}
          </button>
        )}

        {reportable && job && job.state === "done" && (
          <p className="mt-3 text-center text-sm text-signal">
            {job.check ? "Checked" : "Sent"} {job.total} lines · 0 errors
          </p>
        )}
        {reportable && job && job.state === "stopped" && (
          <p className="mt-3 text-center text-sm text-muted">
            Stopped at line {job.acked} of {job.total}.
          </p>
        )}
        {reportable && job && job.state === "error" && (
          <p className="mt-3 text-sm text-danger">{job.error}</p>
        )}
        {err && <p className="mt-3 text-sm text-danger">{err}</p>}
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
