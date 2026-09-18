"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import InlineEdit from "@/components/InlineEdit";
import RetracePanel from "@/components/RetracePanel";
import MachineConsole from "@/components/MachineConsole";
import { useAuth } from "@/lib/auth";
import { api, type Board } from "@/lib/api";
import { useMachine } from "@/lib/machine";
import { DESKTOP } from "@/lib/desktop";

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
  const pathname = usePathname();
  const router = useRouter();

  // The desktop build is a static export with one pre-built copy of this
  // page (id "_") that the Python app serves for every board, so the router
  // only ever knows the placeholder. The real id is in the address bar.
  const [boardId, setBoardId] = useState<string | null>(
    DESKTOP ? null : params.id
  );
  useEffect(() => {
    if (!DESKTOP) {
      setBoardId(params.id);
      return;
    }
    const seg = window.location.pathname.split("/").filter(Boolean);
    setBoardId(seg[2] ?? null);
  }, [params.id, pathname]);
  const { session } = useAuth();

  const [board, setBoard] = useState<Board | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // One copper layer, so one toggle. Double-sided boards are refused at
  // upload, so there is never a second layer to show or hide — a B.Cu
  // control could only ever be a switch with nothing behind it.
  const [copper, setCopper] = useState(true);
  const [toolpath, setToolpath] = useState(false);
  const [replay, setReplay] = useState(0);

  useEffect(() => {
    if (!boardId) return;
    let alive = true;
    (async () => {
      try {
        const b = await api.getBoard(boardId);
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
  }, [boardId]);

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

      {/* The page runs in the order the work does: check the board, watch
          the toolpath, plot it, then watch the wire. Each stage is a real
          step with a real decision in it, which is why they are numbered. */}
      <Stage n="1" title="Board" hint="what was routed from your file">
      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        {/* preview */}
        <section className="panel ticked">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
            <span className="tlabel mr-auto">Preview</span>
            {!traced && (
              <Toggle
                on={copper}
                onClick={() => setCopper((v) => !v)}
                color="fcu"
              >
                {board.layer}
              </Toggle>
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
              key={`${copper}${toolpath}${replay}`}
              tracks={board.tracks}
              strokes={board.strokes}
              width={board.width}
              height={board.height}
              showFront={copper}
              showBack={copper}
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
              <Legend color="var(--color-fcu)" label={`${board.layer} draw`} />
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

            <BedFit width={board.width} height={board.height} />

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

        </section>
      </div>
      </Stage>

      {/* The toolpath and the button that runs it share one screen on
          purpose: you press Plot and watch the same view, instead of
          scrolling between the thing you are watching and the thing you are
          holding. The controls stay put while the toolpath scrolls. */}
      <Stage
        n="2"
        title="Validate and plot"
        hint="a simulation until a job runs, then the machine itself"
      >
        <div className="grid items-start gap-6 lg:grid-cols-[1.5fr_1fr]">
          {board.gcode ? (
            <LiveVisualizer gcode={board.gcode} boardName={board.name} />
          ) : (
            <div className="panel ticked flex h-64 items-center justify-center px-6 text-center text-sm text-muted">
              This board has no G-code to plot. Re-route it from the file, or
              trace it again.
            </div>
          )}
          <div className="lg:sticky lg:top-20">
            <PlotControl
              boardId={board.id}
              boardName={board.name}
              gcodeLines={board.gcodeLines}
            />
          </div>
        </div>
      </Stage>

      <Stage
        n="3"
        title="Console"
        hint="every line sent, and what the controller answered"
      >
        <BoardConsole boardName={board.name} />
      </Stage>

      {/* gcode viewer */}
      <Stage n="4" title="G-code" hint="the file itself, as stored">
      <section className="panel ticked">
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
      </Stage>
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
    <section className="panel ticked">
      {/* The heading tells you which of the two things you are looking at.
          Labelled "simulation" throughout, a live plot reads as an animation
          and the operator has no way to know the difference matters. */}
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="tlabel">
          {mine ? "Toolpath · live" : "Toolpath simulation"}
        </span>
        <span className="font-mono text-xs text-faint">
          {mine
            ? `following ${snap?.conn.port} — drawn as the controller accepts each line`
            : "a preview; what the machine will actually run"}
        </span>
      </div>

      <GcodeVisualizer
        gcode={gcode}
        liveIndex={mine && job ? job.acked : null}
        penPos={mine && snap ? snap.wpos : null}
      />

    </section>
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
  // A plot the USB link cut off: it picks up where the pen stopped.
  const resumable = Boolean(job && mine && job.state === "error" && job.resumable);

  const total = job?.total || gcodeLines;
  const acked = job?.acked ?? 0;
  const pct = total ? Math.round((acked / total) * 100) : 0;

  // What the machine is doing, in words. A bar alone says how far along it
  // is and nothing about what that means — whether it is validating or
  // cutting metal, which line it is on, or whether it is stuck.
  const phase = !job
    ? ""
    : job.state === "running"
    ? job.check
      ? `Dry-checking on ${snap?.conn.port} — parsing every line, nothing moves`
      : `Plotting on ${snap?.conn.port} — machine is ${snap?.state ?? "?"}, pen ${snap?.pen ?? "?"}`
    : job.state === "paused"
    ? "Held. The controller keeps its queue and its work zero."
    : job.state === "done"
    ? job.check
      ? "Every line parsed cleanly. Turn the dry-check off to plot for real."
      : "All lines acknowledged. The pen finishes a moment after this."
    : job.state === "stopped"
    ? "Stopped. The moves already inside the controller were allowed to drain."
    : job.state === "error"
    ? job.resumable
      ? "The USB link dropped. The machine finished the moves it already had and stopped — resume to carry on from there."
      : "Failed. Nothing further was sent."
    : "";

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
          {!live
            ? "Not talking to the server. Is the API running on port 8000?"
            : resumable
            ? `The link dropped at line ${job?.acked} of ${job?.total}. Let the machine finish its last moves, then reconnect: the plot carries on from line ${job?.resumeFrom}, not from the top.`
            : "No machine connected. Plug the controller into this PC over USB and pick its port."}
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

          {phase && <p className="mt-3 text-sm text-ink-soft">{phase}</p>}

          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-xs">
            <Fact label="elapsed" value={clock(job.elapsed)} />
            <Fact
              label="remaining"
              value={job.state === "running" ? `~${clock(job.eta)}` : "—"}
            />
            <Fact
              label="pen at"
              value={
                snap
                  ? `X${snap.wpos[0].toFixed(1)} Y${snap.wpos[1].toFixed(
                      1
                    )} Z${snap.wpos[2].toFixed(1)}`
                  : "—"
              }
            />
            <Fact label="feed" value={snap ? `${Math.round(snap.feed)} mm/min` : "—"} />
          </dl>

          {/* The line at the front of the controller's queue. When a job
              stalls this is the single most useful thing on the page: it
              names what it stopped on. */}
          {job.line && (
            <p className="mt-2 truncate font-mono text-xs text-copper" title={job.line}>
              → {job.line}
            </p>
          )}
        </div>
      )}

      <div className="mt-4">
        {running || paused ? (
          <div className="space-y-1.5">
            <div className="flex gap-1.5">
              {running ? (
                <button
                  className="btn btn-ghost flex-1"
                  disabled={busy}
                  onClick={() => guard(() => api.pauseJob())}
                >
                  Pause
                </button>
              ) : (
                <button
                  className="btn btn-copper flex-1"
                  disabled={busy}
                  onClick={() => guard(() => api.resumeJob())}
                >
                  Resume
                </button>
              )}
              <button
                className="btn btn-ghost flex-1 !border-danger !text-danger"
                disabled={busy}
                onClick={() => guard(() => api.stopJob())}
              >
                Stop
              </button>
            </div>
            {/* Start over without losing the corner you set by hand. Stop
                leaves the pen wherever the file dropped it, which is why
                doing this manually meant an e-stop and zeroing again. */}
            <button
              className="btn btn-ghost w-full"
              disabled={busy}
              onClick={() => guard(() => api.restartJob())}
            >
              {busy ? "restarting…" : "Restart from the top"}
            </button>
            <p className="pt-0.5 text-center font-mono text-[0.7rem] text-faint">
              lifts the pen, waits for the machine to stop, keeps work zero
            </p>
          </div>
        ) : resumable ? (
          <div className="space-y-1.5">
            <button
              className="btn btn-copper w-full"
              disabled={busy}
              onClick={() => guard(() => api.resumeInterrupted())}
            >
              {busy ? "resuming…" : `Resume from line ${job?.resumeFrom}`}
            </button>
            <p className="pt-0.5 text-center font-mono text-[0.7rem] text-faint">
              pen stays where it stopped · redraws the cut stroke · keeps the plot&apos;s zero
            </p>
            <button
              onClick={() => guard(() => api.run(boardId, check))}
              disabled={busy}
              className="btn btn-ghost w-full"
            >
              Discard and plot from the pen
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
        {reportable && job && job.state === "error" && !job.resumable && (
          <p className="mt-3 text-sm text-danger">{job.error}</p>
        )}
        {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      </div>
    </div>
  );
}

/**
 * One step of the job, with a rule under its heading.
 *
 * Numbered because this genuinely is a sequence — a board is looked at,
 * then validated, then plotted, then watched — and an operator halfway
 * through wants to know which of those they are in.
 */
function Stage({
  n,
  title,
  hint,
  children,
}: {
  n: string;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-10 first:mt-0">
      <div className="flex items-baseline gap-3 border-b border-line pb-2">
        <span className="font-mono text-xs text-copper">{n}</span>
        <h2 className="tlabel !text-ink">{title}</h2>
        {hint && (
          <span className="ml-auto hidden truncate font-mono text-xs text-faint sm:inline">
            {hint}
          </span>
        )}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/**
 * The serial link, as text.
 *
 * Read-only here on purpose: this page is for running a file, and a stray
 * hand-typed line in the middle of a plot interleaves with the one being
 * streamed. The machine page is where you talk to the controller yourself.
 */
function BoardConsole({ boardName }: { boardName: string }) {
  const { snap, console: lines, connected } = useMachine();
  const job = snap?.job ?? null;
  const mine =
    (job?.state === "running" || job?.state === "paused") &&
    job?.name === boardName;

  if (!connected) {
    return (
      <div className="panel ticked px-5 py-6 text-sm text-muted">
        Nothing on the wire — no machine is connected.{" "}
        <Link href="/connect" className="text-copper hover:underline">
          Connect a device
        </Link>{" "}
        and every line sent to it shows up here.
      </div>
    );
  }

  return (
    <MachineConsole
      lines={lines}
      onSend={() => {}}
      disabled
      label={null}
      placeholder="Read-only here. Type commands on the machine page."
      status={
        <span className="flex items-center gap-3 font-mono text-xs text-muted">
          <span className="truncate">
            {mine ? (
              <>
                <span className="dot dot-live mr-2 inline-block align-middle" />
                streaming {boardName} to {snap?.conn.port}
              </>
            ) : (
              `idle on ${snap?.conn.port}`
            )}
          </span>
          <Link
            href="/dashboard/device"
            className="flex-none text-copper hover:underline"
          >
            send commands
          </Link>
        </span>
      }
    />
  );
}

/**
 * Whether this board fits the machine, said before anyone presses Plot.
 *
 * The bed is read from the connected machine rather than written down here,
 * so there is one answer to "how big is it" and the page cannot drift from
 * the profile the plot is actually checked against. Nothing is claimed when
 * no machine is connected — an invented bed would be worse than silence.
 */
function BedFit({ width, height }: { width: number; height: number }) {
  const { snap, connected } = useMachine();
  if (!connected || !snap) return null;

  const [bedX, bedY] = snap.conn.travel;
  const fits = width <= bedX && height <= bedY;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex items-baseline justify-between font-mono text-xs">
        <span className="text-muted">bed</span>
        <span className="text-ink">
          {bedX} × {bedY} mm
        </span>
      </div>
      <p
        className={`mt-1.5 text-sm ${fits ? "text-muted" : "text-danger"}`}
      >
        {fits
          ? `This board is ${width} × ${height} mm, and plots down from work zero, its top-left corner.`
          : `This board is ${width} × ${height} mm and will not fit. Re-route it smaller, or trace it at a smaller size.`}
      </p>
    </div>
  );
}

/** Seconds as `m:ss`, or an em dash when there is nothing honest to say. */
function clock(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate text-ink">{value}</dd>
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
