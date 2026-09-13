"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import Logo from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { useMachine } from "@/lib/machine";
import { DESKTOP } from "@/lib/desktop";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: OverviewIcon },
  { href: "/dashboard/projects", label: "Boards", icon: BoardIcon },
  { href: "/dashboard/device", label: "Machine", icon: DeviceIcon },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { session, ready, signOut } = useAuth();
  const { snap, connected, live } = useMachine();
  const router = useRouter();
  const pathname = usePathname();

  // Signed in is the only gate. The dashboard used to also demand a paired
  // device, which made sense when a machine was a property of the account;
  // now it is a USB cable, and looking at your boards should not require one
  // to be plugged in.
  useEffect(() => {
    if (!ready) return;
    if (!session) router.replace("/login");
  }, [ready, session, router]);

  if (!ready || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <span className="tlabel animate-pulse">loading workbench…</span>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-paper">
      {/* sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 flex-none flex-col border-r border-line bg-panel md:flex">
        <div className="flex h-16 items-center border-b border-line px-5">
          <Logo />
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((n) => {
            const active =
              n.href === "/dashboard"
                ? pathname === n.href
                : pathname.startsWith(n.href);
            const Icon = n.icon;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-well text-ink"
                    : "text-muted hover:bg-well/60 hover:text-ink"
                }`}
              >
                <Icon active={active} />
                {n.label}
                {active && <span className="ml-auto h-4 w-0.5 bg-copper" />}
              </Link>
            );
          })}
        </nav>

        {/* machine card */}
        <div className="border-t border-line p-3">
          <Link
            href={connected ? "/dashboard/device" : "/connect"}
            className="block rounded border border-line bg-panel-2 p-3 hover:border-line-strong"
          >
            <span className="tlabel">machine</span>
            {connected ? (
              <>
                <p className="mt-1.5 truncate text-sm text-ink">
                  {snap?.conn.port} · {snap?.state}
                </p>
                <p className="truncate font-mono text-[0.7rem] text-faint">
                  {snap?.conn.firmware}
                </p>
              </>
            ) : (
              <>
                <p className="mt-1.5 text-sm text-muted">not connected</p>
                <p className="font-mono text-[0.7rem] text-copper">
                  connect a machine →
                </p>
              </>
            )}
          </Link>
        </div>
      </aside>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-line bg-paper/85 px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <span className="md:hidden">
              <Logo />
            </span>
            <span className="tlabel hidden md:inline">workbench</span>
            <span className="hidden font-mono text-xs text-faint sm:inline">
              / {session.name}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {/* The machine is one click from every page, not just the two
                that own it: plotting is decided while looking at a board,
                and walking back to the sidebar to plug in breaks that. */}
            <Link
              href={connected ? "/dashboard/device" : "/connect"}
              title={
                connected
                  ? "Open the machine page"
                  : "Pick a serial port and connect"
              }
              className="hidden items-center gap-2 rounded border border-line px-2.5 py-1.5 font-mono text-xs text-muted transition-colors hover:border-line-strong hover:text-ink sm:flex"
            >
              {/* Two separate facts, deliberately not merged: whether this
                  browser is talking to the server, and whether the server is
                  talking to the machine. */}
              <span className={`dot ${live ? "dot-live" : ""}`} />
              {connected
                ? `${snap?.conn.port} · ${snap?.state}`
                : live
                ? "no machine"
                : "server offline"}
            </Link>
            {!connected && (
              <Link href="/connect" className="btn btn-copper !px-3 !py-1.5">
                Connect device
              </Link>
            )}
            {!DESKTOP && (
              <button
                onClick={() => {
                  signOut();
                  router.push("/");
                }}
                className="tlabel hover:text-danger"
              >
                Sign out
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 pb-20 md:pb-0">{children}</main>
      </div>

      {/* mobile bottom nav — sidebar is desktop-only */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-panel/95 backdrop-blur-md md:hidden">
        {NAV.map((n) => {
          const active =
            n.href === "/dashboard"
              ? pathname === n.href
              : pathname.startsWith(n.href);
          const Icon = n.icon;
          return (
            <Link
              key={n.href}
              href={n.href}
              className={`relative flex flex-1 flex-col items-center gap-1 py-2.5 text-[0.65rem] ${
                active ? "text-copper" : "text-muted"
              }`}
            >
              {active && (
                <span className="absolute left-1/2 top-0 h-0.5 w-10 -translate-x-1/2 bg-copper" />
              )}
              <Icon active={active} />
              {n.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

/* ---- line icons (currentColor) ---- */
function base(active?: boolean) {
  return {
    width: 16,
    height: 16,
    fill: "none",
    stroke: active ? "var(--color-copper)" : "currentColor",
    strokeWidth: 1.5,
  } as const;
}
function OverviewIcon({ active }: { active?: boolean }) {
  return (
    <svg {...base(active)} viewBox="0 0 16 16">
      <rect x="2" y="2" width="5" height="5" />
      <rect x="9" y="2" width="5" height="5" />
      <rect x="2" y="9" width="5" height="5" />
      <rect x="9" y="9" width="5" height="5" />
    </svg>
  );
}
function BoardIcon({ active }: { active?: boolean }) {
  return (
    <svg {...base(active)} viewBox="0 0 16 16">
      <rect x="2" y="2" width="12" height="12" rx="1" />
      <path d="M2 6h4l2 3h6" />
      <circle cx="6" cy="6" r="0.8" fill="currentColor" />
    </svg>
  );
}
function DeviceIcon({ active }: { active?: boolean }) {
  return (
    <svg {...base(active)} viewBox="0 0 16 16">
      <rect x="3" y="3" width="10" height="10" rx="1" />
      <path d="M6 1v2M10 1v2M6 13v2M10 13v2M1 6h2M1 10h2M13 6h2M13 10h2" />
    </svg>
  );
}
