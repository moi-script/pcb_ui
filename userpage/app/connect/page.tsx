"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Logo from "@/components/Logo";
import { api, type PortInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMachine } from "@/lib/machine";

export default function Connect() {
  const { session } = useAuth();
  const router = useRouter();
  const { snap, connected } = useMachine();
  // Connecting reopens the port, which reboots the Arduino: never mid-plot.
  const plotting =
    snap?.job?.state === "running" || snap?.job?.state === "paused";

  const [ports, setPorts] = useState<PortInfo[]>([]);
  const [bauds, setBauds] = useState<number[]>([115200]);
  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [scanning, setScanning] = useState(true);
  const [busy, setBusy] = useState(false);
  const [firmware, setFirmware] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const email = session?.email;

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    try {
      const list = await api.machinePorts();
      setPorts(list.ports);
      setBauds(list.bauds);

      // The backend fills `suggested` only when exactly one candidate is
      // present. Falling back to "the first port" when it declined to guess
      // would undo that on purpose, and the wrong choice moves a machine.
      let pick = list.suggested ?? "";
      let rate = 115200;
      if (email) {
        try {
          const last = await api.machineLast(email);
          if (last && list.ports.some((p) => p.device === last.port)) {
            pick = last.port;
            rate = last.baud;
          }
        } catch {
          // A missing crumb is not an error worth showing anyone.
        }
      }
      setPort((current) =>
        current && list.ports.some((p) => p.device === current) ? current : pick
      );
      setBaud(rate);
    } catch (e) {
      setError((e as Error).message);
      setPorts([]);
    } finally {
      setScanning(false);
    }
  }, [email]);

  useEffect(() => {
    void scan();
  }, [scan]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    if (!port) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.machineConnect(port, baud, email);
      setFirmware(res.firmware);
      router.push("/dashboard/device");
    } catch (err) {
      // Verbatim. The backend's message already names the port and the
      // reason; "Connection failed" would throw away the useful half.
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="substrate flex min-h-screen flex-col px-6 py-8 sm:px-12">
      <Logo />

      <div className="flex flex-1 items-center justify-center">
        <div className="w-full max-w-lg">
          <div className="text-center">
            <span className="tlabel">connect your machine</span>
            <h1 className="mt-3 text-3xl tracking-tight text-ink">
              Pick the serial port.
            </h1>
            <p className="mx-auto mt-3 max-w-sm text-sm text-muted">
              Plug the controller into this PC over USB. The server owns the
              port — a browser tab can&apos;t open one.
            </p>
          </div>

          {snap?.job?.resumable && snap.job.state === "error" && (
            <div className="mt-8 border border-copper px-4 py-3 text-sm">
              <p className="text-ink">
                &apos;{snap.job.name}&apos; was cut off at line {snap.job.acked}{" "}
                of {snap.job.total} when the USB link dropped.
              </p>
              <p className="mt-1 text-xs text-muted">
                Don&apos;t move the pen. Reconnect, then open the board and press
                Resume — it carries on from line {snap.job.resumeFrom}, not from
                the top.
              </p>
            </div>
          )}

          {connected && (
            <div className="mt-8 border border-copper px-4 py-3 text-sm">
              <p className="text-ink">
                Already connected to{" "}
                <span className="font-mono">{snap?.conn.port}</span>
                {plotting ? ` and plotting '${snap?.job?.name}'.` : "."}
              </p>
              <p className="mt-1 text-xs text-muted">
                {plotting
                  ? "Connecting again would reset the controller and end the plot. Stop it first."
                  : "Connecting again resets the controller."}
              </p>
              <Link href="/dashboard/device" className="btn btn-primary mt-3">
                Go to the machine →
              </Link>
            </div>
          )}

          <div className="panel ticked mt-8 p-6">
            <form onSubmit={connect}>
              <div className="flex items-baseline justify-between">
                <label className="tlabel">Serial port</label>
                <button
                  type="button"
                  onClick={() => void scan()}
                  className="text-xs text-faint hover:text-copper"
                >
                  {scanning ? "scanning…" : "rescan"}
                </button>
              </div>

              {ports.length === 0 && !scanning ? (
                <p className="mt-3 border border-line-strong px-3 py-4 text-center text-sm text-muted">
                  No serial ports found — is the cable plugged in?
                </p>
              ) : (
                <div className="mt-2 space-y-1.5">
                  {ports.map((p) => (
                    <label
                      key={p.device}
                      className={`flex cursor-pointer items-center gap-3 border px-3 py-2.5 ${
                        port === p.device
                          ? "border-copper"
                          : "border-line-strong hover:border-line"
                      }`}
                    >
                      <input
                        type="radio"
                        name="port"
                        className="accent-copper"
                        checked={port === p.device}
                        onChange={() => setPort(p.device)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="font-mono text-sm text-ink">
                          {p.device}
                        </span>
                        <span className="ml-2 text-xs text-muted">
                          {p.description}
                        </span>
                        {p.chip && (
                          <span className="ml-2 font-mono text-[0.7rem] text-faint">
                            {p.chip}
                          </span>
                        )}
                      </span>
                      {p.likely_controller && (
                        <span className="tlabel flex-none text-signal">
                          likely
                        </span>
                      )}
                    </label>
                  ))}
                </div>
              )}

              <label className="tlabel mt-5 block">Baud rate</label>
              <select
                className="field mt-2"
                value={baud}
                onChange={(e) => setBaud(Number(e.target.value))}
              >
                {bauds.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>

              {error && (
                <p className="mt-4 text-sm text-danger">{error}</p>
              )}
              {firmware && !error && (
                <p className="mt-4 font-mono text-sm text-signal">{firmware}</p>
              )}

              <button
                className="btn btn-copper mt-5 w-full"
                type="submit"
                disabled={!port || busy || plotting}
              >
                {busy ? "connecting…" : plotting ? "plot running" : "Connect"}
              </button>
            </form>

            <p className="mt-5 border-t border-line pt-4 text-xs text-faint">
              Connecting resets the controller and puts work zero where the pen
              is now. Park the pen at the top-left of where the board goes (the
              plot runs down from there), or set zero
              on the Machine page before plotting.
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-faint">
            No hardware? Start the API with{" "}
            <span className="font-mono text-ink">TRACEWORKS_SIM=1</span> and
            connect to the port named SIM.
          </p>
        </div>
      </div>
    </div>
  );
}
