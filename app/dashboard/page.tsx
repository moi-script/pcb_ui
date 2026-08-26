"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import { useAuth } from "@/lib/auth";
import { api, type Board } from "@/lib/api";

const statusColor: Record<string, string> = {
  plotted: "text-signal",
  ready: "text-copper",
  generating: "text-warn",
  draft: "text-faint",
};

export default function Overview() {
  const { session } = useAuth();
  const [boards, setBoards] = useState<Board[]>([]);
  const [featured, setFeatured] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    let alive = true;
    (async () => {
      try {
        const list = await api.listBoards(session.email);
        if (!alive) return;
        setBoards(list);
        if (list.length) setFeatured(await api.getBoard(list[0].id));
      } catch {
        /* leave empty on error */
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [session]);

  const device = session?.device;
  const totalTracks = boards.reduce((a, b) => a + b.fcu + b.bcu, 0);
  const before = boards.reduce((a, b) => a + b.penUpBefore, 0);
  const after = boards.reduce((a, b) => a + b.penUpAfter, 0);
  const saved = before ? Math.round((1 - after / before) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-end justify-between">
        <div>
          <span className="tlabel">Overview</span>
          <h1 className="mt-1 text-2xl tracking-tight text-ink">
            Your bench right now.
          </h1>
        </div>
        <Link href="/dashboard/projects" className="btn btn-copper">
          + New board
        </Link>
      </div>

      {/* stat strip */}
      <div className="mt-6 grid gap-px overflow-hidden rounded border border-line bg-line sm:grid-cols-4">
        <StatCell k="Paired device" v={device?.id ?? "—"} sub={device?.alias ?? ""} accent />
        <StatCell k="Boards" v={String(boards.length)} sub="routed & saved" />
        <StatCell k="Tracks routed" v={String(totalTracks)} sub="across boards" />
        <StatCell k="Travel saved" v={`${saved}%`} sub="less pen-up" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* recent boards */}
        <section className="panel ticked">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <span className="tlabel">Recent boards</span>
            <Link
              href="/dashboard/projects"
              className="text-xs text-copper hover:underline"
            >
              view all
            </Link>
          </div>

          {loading ? (
            <p className="tlabel animate-pulse px-5 py-8">loading…</p>
          ) : boards.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <p className="text-sm text-muted">No boards yet.</p>
              <Link
                href="/dashboard/projects"
                className="btn btn-ghost mt-4"
              >
                Upload a .kicad_pcb
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-line">
              {boards.map((b) => (
                <Link
                  key={b.id}
                  href={`/dashboard/projects/${b.id}`}
                  className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-well/50"
                >
                  {(b.strokes?.length || b.tracks?.length) ? (
                    <div className="flex h-10 w-16 flex-none items-center justify-center overflow-hidden rounded border border-line bg-panel-2 p-1">
                      <PcbBoard
                        tracks={b.tracks}
                        strokes={b.strokes}
                        width={b.width}
                        height={b.height}
                        className="h-full w-full"
                      />
                    </div>
                  ) : (
                    <BoardChip />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">{b.name}</p>
                    <p className="font-mono text-[0.7rem] text-faint">
                      {b.filename}
                    </p>
                  </div>
                  <div className="hidden text-right sm:block">
                    <p className="font-mono text-sm text-ink">
                      {b.fcu + b.bcu}
                    </p>
                    <p className="tlabel !text-[0.6rem]">tracks</p>
                  </div>
                  <span
                    className={`tlabel w-20 text-right ${
                      statusColor[b.status] ?? "text-faint"
                    }`}
                  >
                    {b.status}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* featured board + device */}
        <section className="space-y-6">
          {featured && (
            <div className="panel ticked p-1.5">
              <div className="flex items-center justify-between border-b border-line px-3 py-2">
                <span className="tlabel">{featured.name} · {featured.layer}</span>
                <span className="tlabel !text-copper">latest</span>
              </div>
              <div className="panel-2 aspect-[16/10] p-3">
                <PcbBoard
                  animate
                  tracks={featured.tracks}
                  strokes={featured.strokes}
                  width={featured.width}
                  height={featured.height}
                  className="h-full w-full"
                />
              </div>
              <div className="border-t border-line p-3">
                <Link
                  href={`/dashboard/projects/${featured.id}`}
                  className="btn btn-primary w-full"
                >
                  Open & plot →
                </Link>
              </div>
            </div>
          )}

          {device && (
            <div className="panel p-5">
              <span className="tlabel">Machine profile</span>
              <dl className="mt-3 space-y-2 font-mono text-xs">
                <PRow k="controller" v={device.controller} />
                <PRow k="firmware" v={device.firmware} />
                <PRow k="bed" v={`${device.bed} mm`} />
                <PRow k="pen up / down" v={`Z${device.penUpZ} / Z${device.penDownZ}`} />
                <PRow
                  k="feeds"
                  v={`travel ${device.travelFeed} · draw ${device.drawFeed}`}
                />
              </dl>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCell({
  k,
  v,
  sub,
  accent,
}: {
  k: string;
  v: string;
  sub: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-panel-2 p-5">
      <p className="tlabel">{k}</p>
      <p className={`mt-2 font-mono text-lg ${accent ? "text-copper" : "text-ink"}`}>
        {v}
      </p>
      <p className="mt-0.5 text-xs text-muted">{sub}</p>
    </div>
  );
}

function PRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-faint">{k}</dt>
      <dd className="truncate text-ink-soft">{v}</dd>
    </div>
  );
}

// small placeholder glyph for list rows (tracks aren't loaded in the summary)
function BoardChip() {
  return (
    <div className="flex h-10 w-16 flex-none items-center justify-center rounded border border-line bg-panel-2">
      <svg width="30" height="18" viewBox="0 0 30 18" fill="none">
        <path
          d="M2 13h6l4-8h10M8 13v3M22 5h6"
          stroke="var(--color-copper)"
          strokeWidth="1.1"
        />
        <circle cx="2" cy="13" r="1.4" fill="var(--color-ink)" />
        <circle cx="28" cy="5" r="1.6" fill="var(--color-copper)" />
      </svg>
    </div>
  );
}
