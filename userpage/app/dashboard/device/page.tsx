"use client";

import { useRouter } from "next/navigation";
import InlineEdit from "@/components/InlineEdit";
import { useAuth } from "@/lib/auth";

export default function DevicePage() {
  const { session, unpair, renameDevice } = useAuth();
  const router = useRouter();

  const device = session?.device;
  if (!device) return null;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <span className="tlabel">Device</span>
      <h1 className="mt-1 text-2xl tracking-tight text-ink">
        <InlineEdit
          value={device.alias}
          ariaLabel="Rename device"
          onSave={async (next) => {
            const r = await renameDevice(next);
            if (!r.ok) throw new Error(r.error);
          }}
        />
      </h1>

      {/* identity */}
      <div className="panel ticked mt-6 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="tlabel">Device ID</span>
            <p className="mt-1 font-mono text-2xl tracking-wider text-ink">
              <span className="text-copper">
                {device.id.split("-")[0]}
              </span>
              -{device.id.split("-").slice(1).join("-")}
            </p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-sm border border-line-strong px-3 py-1.5">
            <span className="tlabel">paired</span>
          </span>
        </div>

        <dl className="mt-6 grid gap-px overflow-hidden rounded border border-line bg-line sm:grid-cols-2">
          <Field k="Controller" v={device.controller} />
          <Field k="Firmware" v={device.firmware} />
          <Field k="Connection" v={`${device.connection} · ${device.port}`} />
          <Field k="Bed size" v={`${device.bed} mm`} />
        </dl>
      </div>

      {/* machine profile */}
      <div className="panel ticked mt-6 p-6">
        <div className="flex items-center justify-between">
          <span className="tlabel">Machine profile</span>
          <span className="font-mono text-[0.7rem] text-faint">
            must match FluidNC config.yaml
          </span>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Profile label="Pen up (Z)" value={`${device.penUpZ} mm`} hint="servo lifted" />
          <Profile label="Pen down (Z)" value={`${device.penDownZ} mm`} hint="servo on paper" />
          <Profile label="Travel feed" value={`${device.travelFeed} mm/min`} hint="G0 rapid" />
          <Profile label="Draw feed" value={`${device.drawFeed} mm/min`} hint="G1 draw" />
        </div>
        <p className="mt-4 font-mono text-[0.7rem] text-muted">
          These line up with the servo pulse range in your FluidNC config. Keep
          the two in step so the pen lifts and touches down where you expect.
        </p>
      </div>

      {/* danger zone */}
      <div className="panel mt-6 border-danger/30 p-6">
        <span className="tlabel !text-danger">Unpair device</span>
        <p className="mt-2 max-w-lg text-sm text-muted">
          Release {device.id} from your account. We keep its job history, but
          you won&apos;t be able to send anything to it until you pair it again
          with its device ID.
        </p>
        <button
          onClick={async () => {
            await unpair();
            router.push("/connect");
          }}
          className="btn btn-ghost mt-4 !border-danger !text-danger hover:!bg-danger/5"
        >
          Unpair this device
        </button>
      </div>
    </div>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div className="bg-panel-2 p-4">
      <p className="tlabel !text-[0.6rem]">{k}</p>
      <p className="mt-1 font-mono text-sm text-ink">{v}</p>
    </div>
  );
}

function Profile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded border border-line bg-panel-2 p-4">
      <p className="tlabel !text-[0.6rem]">{label}</p>
      <p className="mt-1 font-mono text-lg text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-faint">{hint}</p>
    </div>
  );
}
