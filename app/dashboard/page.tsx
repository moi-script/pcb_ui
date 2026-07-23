import Link from "next/link";
import PcbBoard from "@/components/PcbBoard";
import { projects, device } from "@/lib/data";

const statusColor: Record<string, string> = {
  plotted: "text-signal",
  ready: "text-copper",
  generating: "text-warn",
  draft: "text-faint",
};

export default function Overview() {
  const totalTracks = projects.reduce((a, p) => a + p.tracks, 0);
  const saved = Math.round(
    (1 -
      projects.reduce((a, p) => a + p.penUpAfter, 0) /
        projects.reduce((a, p) => a + p.penUpBefore, 0)) *
      100
  );

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
        <StatCell k="Paired device" v={device.id} sub={device.alias} accent />
        <StatCell k="Boards" v={String(projects.length)} sub="in workspace" />
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
          <div className="divide-y divide-line">
            {projects.map((p) => (
              <Link
                key={p.id}
                href={`/dashboard/projects/${p.id}`}
                className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-well/50"
              >
                <div className="h-10 w-16 flex-none rounded border border-line bg-panel-2 p-1">
                  <PcbBoard showBack={false} className="h-full w-full" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{p.name}</p>
                  <p className="font-mono text-[0.7rem] text-faint">
                    {p.board}
                  </p>
                </div>
                <div className="hidden text-right sm:block">
                  <p className="font-mono text-sm text-ink">{p.tracks}</p>
                  <p className="tlabel !text-[0.6rem]">tracks</p>
                </div>
                <span
                  className={`tlabel w-20 text-right ${statusColor[p.status]}`}
                >
                  {p.status}
                </span>
              </Link>
            ))}
          </div>
        </section>

        {/* device + featured board */}
        <section className="space-y-6">
          <div className="panel ticked p-1.5">
            <div className="flex items-center justify-between border-b border-line px-3 py-2">
              <span className="tlabel">labExam · F.Cu</span>
              <span className="tlabel !text-copper">ready</span>
            </div>
            <div className="panel-2 aspect-[16/10] p-3">
              <PcbBoard animate showBack className="h-full w-full" />
            </div>
            <div className="border-t border-line p-3">
              <Link
                href="/dashboard/projects/labexam"
                className="btn btn-primary w-full"
              >
                Open & plot →
              </Link>
            </div>
          </div>

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
      <p
        className={`mt-2 font-mono text-lg ${
          accent ? "text-copper" : "text-ink"
        }`}
      >
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
