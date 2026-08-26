"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Logo from "@/components/Logo";
import { useAuth, DEMO_DEVICE_ID } from "@/lib/auth";

type Phase = "idle" | "pairing" | "bound" | "error";

const STEPS = [
  "opening link to controller",
  "reading $I firmware identity",
  "verifying device signature",
  "binding to your account",
];

export default function Connect() {
  const { pairDevice } = useAuth();
  const router = useRouter();
  const [id, setId] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // drive the handshake animation, then actually pair via the API
  useEffect(() => {
    if (phase !== "pairing") return;
    if (step < STEPS.length) {
      const t = setTimeout(() => setStep((s) => s + 1), 620);
      return () => clearTimeout(t);
    }
    let cancelled = false;
    (async () => {
      const res = await pairDevice(normalize(id));
      if (cancelled) return;
      if (res.ok) setPhase("bound");
      else {
        setError(res.error ?? "Pairing failed.");
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, step, id, pairDevice]);

  function start(e: React.FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setStep(0);
    setPhase("pairing");
  }

  return (
    <div className="substrate flex min-h-screen flex-col px-6 py-8 sm:px-12">
      <Logo />

      <div className="flex flex-1 items-center justify-center">
        <div className="w-full max-w-lg">
          <div className="text-center">
            <span className="tlabel">Step 2 of 2 · pair your machine</span>
            <h1 className="mt-3 text-3xl tracking-tight text-ink">
              Enter your device ID.
            </h1>
            <p className="mx-auto mt-3 max-w-sm text-sm text-muted">
              It&apos;s printed on the controller and shown in the FluidNC
              console when you type <span className="font-mono text-ink">$I</span>.
            </p>
          </div>

          <div className="panel ticked mt-8 p-6">
            {phase === "idle" || phase === "error" ? (
              <form onSubmit={start}>
                <label className="tlabel">Device ID</label>
                <input
                  className="field mt-2 text-center !text-lg tracking-[0.2em]"
                  value={id}
                  onChange={(e) => setId(e.target.value.toUpperCase())}
                  placeholder="TW-XXXX-XXXX"
                  autoFocus
                />
                {phase === "error" && (
                  <p className="mt-3 text-center text-sm text-danger">
                    {error ?? "Couldn't pair that ID. Try again."}
                  </p>
                )}
                <button className="btn btn-copper mt-4 w-full" type="submit">
                  Pair device
                </button>
                <button
                  type="button"
                  onClick={() => setId(DEMO_DEVICE_ID)}
                  className="mt-3 w-full text-center text-xs text-faint hover:text-copper"
                >
                  use the demo machine · {DEMO_DEVICE_ID}
                </button>
              </form>
            ) : phase === "pairing" ? (
              <div className="py-2">
                <div className="mb-5 flex items-center justify-center gap-2">
                  <span className="dot dot-live" />
                  <span className="font-mono text-sm tracking-wider text-ink">
                    {normalize(id)}
                  </span>
                </div>
                <ul className="space-y-3">
                  {STEPS.map((s, i) => (
                    <li
                      key={s}
                      className="flex items-center gap-3 font-mono text-sm"
                    >
                      <Marker done={i < step} active={i === step} />
                      <span
                        className={
                          i < step
                            ? "text-ink-soft"
                            : i === step
                            ? "text-ink"
                            : "text-faint"
                        }
                      >
                        {s}
                        {i === step && <Dots />}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="py-4 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-signal">
                  <Check />
                </div>
                <p className="mt-4 font-mono text-lg tracking-wider text-ink">
                  {DEMO_DEVICE_ID}
                </p>
                <p className="mt-1 text-sm text-signal">
                  Bound to your account.
                </p>
                <button
                  onClick={() => router.push("/dashboard")}
                  className="btn btn-primary mt-6 w-full"
                >
                  Open the workbench →
                </button>
              </div>
            )}
          </div>

          <p className="mt-6 text-center text-xs text-faint">
            One machine can be bound to one account at a time.
          </p>
        </div>
      </div>
    </div>
  );
}

function normalize(s: string) {
  return s.trim().toUpperCase();
}

function Marker({ done, active }: { done: boolean; active: boolean }) {
  if (done)
    return (
      <span className="flex h-4 w-4 flex-none items-center justify-center bg-signal text-panel-2">
        <Check small />
      </span>
    );
  return (
    <span
      className={`h-4 w-4 flex-none border ${
        active ? "border-copper" : "border-line-strong"
      }`}
    />
  );
}

function Dots() {
  return <span className="animate-pulse">…</span>;
}

function Check({ small }: { small?: boolean }) {
  const s = small ? 10 : 20;
  return (
    <svg width={s} height={s} viewBox="0 0 20 20" fill="none">
      <path
        d="M4 10.5l4 4 8-9"
        stroke={small ? "currentColor" : "var(--color-signal)"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
