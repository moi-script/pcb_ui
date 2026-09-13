"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Dro from "@/components/Dro";
import JogPad from "@/components/JogPad";
import MachineConsole from "@/components/MachineConsole";
import { api } from "@/lib/api";
import { useMachine } from "@/lib/machine";

export default function MachinePage() {
  const { snap, console: lines, connected, live, ready } = useMachine();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const state = snap?.state ?? "";
  const alarm = state.startsWith("Alarm");
  const jobRunning =
    snap?.job?.state === "running" || snap?.job?.state === "paused";

  async function guard(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  // Not yet heard from the server is not the same as "no machine". Showing
  // a Connect button here mid-plot invited a reconnect that reset the board.
  if (!ready) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <span className="tlabel animate-pulse">reading the machine…</span>
      </div>
    );
  }

  if (!connected) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <span className="tlabel">Machine</span>
        <h1 className="mt-1 text-2xl tracking-tight text-ink">
          No machine connected.
        </h1>
        <div className="panel ticked mt-6 p-6">
          <p className="text-sm text-muted">
            {live
              ? "The server is running but has no serial port open. Plug the controller into this PC over USB and pick its port."
              : "Not talking to the server. Is the API running on port 8000?"}
          </p>
          <Link href="/connect" className="btn btn-copper mt-5">
            Connect a machine →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      {!live && (
        <div className="mb-4 border border-warn px-4 py-2 font-mono text-xs text-warn">
          reconnecting to the server… the readings below may be stale
        </div>
      )}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <span className="tlabel">Machine</span>
          <h1 className="mt-1 font-mono text-2xl tracking-tight text-ink">
            {snap?.conn.port}
            <span className="ml-3 text-sm text-faint">
              {snap?.conn.baud} baud
            </span>
          </h1>
          <p className="mt-1 font-mono text-xs text-muted">
            {snap?.conn.firmware}
          </p>
        </div>
        <button
          className="btn btn-ghost"
          onClick={() =>
            guard(async () => {
              await api.machineDisconnect();
              router.push("/connect");
            })
          }
        >
          Disconnect
        </button>
      </div>

      {error && (
        <p className="mt-4 border border-danger px-4 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <Dro snap={snap} />

          <JogPad
            disabled={!connected || alarm || jobRunning}
            onJog={(axis, distance) =>
              guard(() => api.jog(axis, distance))
            }
          />

          <div className="panel p-5">
            <span className="tlabel">Work zero</span>
            <p className="mt-2 text-xs text-muted">
              Connecting reset the controller and put work zero where the pen
              is. A plot starts there, at its top-left corner, and runs down.
              To start somewhere else, jog there and zero X + Y. Z is the pen
              servo and is never zeroed.
            </p>
            <div className="mt-4 grid grid-cols-3 gap-1.5">
              {["X", "Y", "XY"].map((axes) => (
                <button
                  key={axes}
                  className="btn btn-ghost font-mono text-xs"
                  disabled={jobRunning}
                  onClick={() => guard(() => api.zero(axes))}
                >
                  {axes === "XY" ? "zero X + Y" : `zero ${axes}`}
                </button>
              ))}
            </div>

            <div className="mt-4 flex gap-1.5">
              {/* grbl_servo_z has no limit switches and ships with homing
                  off ($22=0), so $H can only ever answer error:5. Set
                  work zero by hand with the zero buttons instead. */}
              <button
                className="btn btn-ghost flex-1"
                disabled
                title="No limit switches on grbl_servo_z: jog to the top-left corner and zero X + Y instead"
              >
                Home ($H)
              </button>
              <button
                className={`flex-1 btn ${alarm ? "btn-copper" : "btn-ghost"}`}
                onClick={() => guard(() => api.unlock())}
              >
                Unlock ($X)
              </button>
            </div>
            <p className="mt-2 font-mono text-[0.7rem] text-faint">
              no homing on this firmware — jog to the top-left corner, then zero X + Y
            </p>
          </div>

          {/* Set apart from every other control: an e-stop next to a jog
              button is an e-stop that gets pressed by accident, and a jog
              button next to an e-stop is a jog that never happens. */}
          <div className="border border-danger p-5">
            <span className="tlabel !text-danger">Emergency stop</span>
            <p className="mt-2 text-xs text-muted">
              Soft-resets the controller immediately. Motion stops mid-move,
              position becomes unknown, and work zero is lost.
            </p>
            <button
              className="btn mt-4 w-full !border-danger !bg-danger !text-paper"
              onClick={() => guard(() => api.estop())}
            >
              E-STOP
            </button>
          </div>
        </div>

        <MachineConsole
          lines={lines}
          disabled={!connected}
          onSend={(line) => guard(() => api.command(line))}
        />
      </div>
    </div>
  );
}
