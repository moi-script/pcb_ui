"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Uploader from "@/components/Uploader";
import { useAuth } from "@/lib/auth";
import { api, type Board } from "@/lib/api";

const statusColor: Record<string, string> = {
  plotted: "text-signal border-signal/40",
  ready: "text-copper border-copper/40",
  generating: "text-warn border-warn/40",
  draft: "text-faint border-line-strong",
};

export default function Projects() {
  const { session } = useAuth();
  const [boards, setBoards] = useState<Board[]>([]);
  const [loading, setLoading] = useState(true);
  const [armed, setArmed] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    let alive = true;
    (async () => {
      try {
        const list = await api.listBoards(session.email);
        if (alive) setBoards(list);
      } catch {
        /* ignore */
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [session]);

  async function remove(id: string) {
    setDeleting(id);
    try {
      await api.deleteBoard(id);
      setBoards((bs) => bs.filter((b) => b.id !== id));
    } catch {
      /* leave the board in place on error */
    } finally {
      setDeleting(null);
      setArmed(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-end justify-between">
        <div>
          <span className="tlabel">Boards</span>
          <h1 className="mt-1 text-2xl tracking-tight text-ink">
            Your workspace.
          </h1>
        </div>
      </div>

      <div className="mt-6">
        <Uploader />
      </div>

      {loading ? (
        <p className="tlabel mt-8 animate-pulse">loading boards…</p>
      ) : boards.length === 0 ? (
        <p className="mt-8 text-sm text-muted">
          Nothing here yet. Drop a <span className="font-mono">.kicad_pcb</span>{" "}
          above to route your first board.
        </p>
      ) : (
        <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {boards.map((b) => (
            <Link
              key={b.id}
              href={`/dashboard/projects/${b.id}`}
              className="panel ticked group relative overflow-hidden transition-shadow hover:border-line-strong"
            >
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <span className="truncate font-mono text-sm text-ink">
                  {b.name}
                </span>
                {armed === b.id ? (
                  <span className="flex items-center gap-2 font-mono text-[0.7rem]">
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        remove(b.id);
                      }}
                      disabled={deleting === b.id}
                      className="text-danger hover:underline disabled:opacity-50"
                    >
                      {deleting === b.id ? "deleting…" : "delete?"}
                    </button>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setArmed(null);
                      }}
                      className="text-faint hover:text-muted"
                    >
                      cancel
                    </button>
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <span
                      className={`tlabel rounded-sm border px-1.5 py-0.5 !text-[0.6rem] ${
                        statusColor[b.status] ?? statusColor.draft
                      }`}
                    >
                      {b.status}
                    </span>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setArmed(b.id);
                      }}
                      aria-label="Delete board"
                      className="text-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                    >
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path
                          d="M2.5 3.5h9M5 3.5V2.2h4V3.5M4 3.5l.5 8h5l.5-8"
                          stroke="currentColor"
                          strokeWidth="1.1"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </span>
                )}
              </div>
              <div className="panel-2 flex aspect-[16/10] items-center justify-center p-4">
                <BoardGlyph />
              </div>
              <dl className="grid grid-cols-3 divide-x divide-line border-t border-line text-center">
                <Cell k="tracks" v={String(b.fcu + b.bcu)} />
                <Cell k="nets" v={String(b.nets)} />
                <Cell k="mm" v={String(b.width)} />
              </dl>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function Cell({ k, v }: { k: string; v: string }) {
  return (
    <div className="px-2 py-2.5">
      <p className="font-mono text-sm text-ink">{v}</p>
      <p className="tlabel !text-[0.6rem]">{k}</p>
    </div>
  );
}

function BoardGlyph() {
  return (
    <svg width="120" height="60" viewBox="0 0 120 60" fill="none" opacity="0.9">
      <path
        d="M8 44h20l14-28h40M28 44v10M42 16v-8M82 16h30M60 44h30"
        stroke="var(--color-copper)"
        strokeWidth="1.4"
      />
      <path d="M10 30h26M96 44h14" stroke="var(--color-bcu)" strokeWidth="1.2" opacity="0.6" />
      <circle cx="8" cy="44" r="2.4" fill="var(--color-ink)" />
      <circle cx="112" cy="16" r="2.8" fill="var(--color-copper)" />
    </svg>
  );
}
