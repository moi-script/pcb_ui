import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import Uploader from "@/components/Uploader";
import { projects } from "@/lib/data";

const statusColor: Record<string, string> = {
  plotted: "text-signal border-signal/40",
  ready: "text-copper border-copper/40",
  generating: "text-warn border-warn/40",
  draft: "text-faint border-line-strong",
};

export default function Projects() {
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

      {/* upload dropzone (real file picker + drag-drop) */}
      <div className="mt-6">
        <Uploader />
      </div>

      {/* grid */}
      <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((p) => (
          <Link
            key={p.id}
            href={`/dashboard/projects/${p.id}`}
            className="panel ticked group overflow-hidden transition-shadow hover:border-line-strong"
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <span className="truncate font-mono text-sm text-ink">
                {p.name}
              </span>
              <span
                className={`tlabel rounded-sm border px-1.5 py-0.5 !text-[0.6rem] ${statusColor[p.status]}`}
              >
                {p.status}
              </span>
            </div>
            <div className="panel-2 aspect-[16/10] p-4">
              <PcbBoard showBack className="h-full w-full" />
            </div>
            <dl className="grid grid-cols-3 divide-x divide-line border-t border-line text-center">
              <Cell k="tracks" v={String(p.tracks)} />
              <Cell k="nets" v={String(p.nets)} />
              <Cell k="mm" v={p.size.split(" ")[0]} />
            </dl>
          </Link>
        ))}
      </div>
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
