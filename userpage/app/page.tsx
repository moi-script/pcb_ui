import Link from "next/link";
import MarketingNav from "@/components/MarketingNav";
import Footer from "@/components/Footer";
import PcbBoard from "@/components/PcbBoard";
import DesktopHome from "@/components/DesktopHome";
import { pipeline } from "@/lib/data";
import { DESKTOP, WINDOWS_DOWNLOAD_URL } from "@/lib/desktop";

export default function Landing() {
  if (DESKTOP) return <DesktopHome />;
  return (
    <div className="substrate min-h-screen">
      <MarketingNav />

      {/* ---------------------------------------------------------------- hero */}
      <section className="mx-auto max-w-6xl px-6 pt-16 pb-20 md:pt-24">
        <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_1fr]">
          <div>
            <span className="tlabel">KiCad → G-code → your plotter</span>
            <h1 className="mt-5 text-4xl leading-[1.05] tracking-tight text-ink sm:text-5xl md:text-[3.5rem]">
              Plot a real PCB
              <br />
              from your browser.
            </h1>
            <p className="mt-6 max-w-md text-lg leading-relaxed text-ink-soft">
              Give TraceWorks a single-layer KiCad board and it works out a pen
              plot that doesn&apos;t waste motion. Plug your Arduino plotter in
              over USB, look over the toolpath, and send it straight from
              TraceWorks. You won&apos;t need a separate G-code sender.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/signup" className="btn btn-copper">
                Create an account
              </Link>
              <a href={WINDOWS_DOWNLOAD_URL} className="btn btn-primary">
                <DownloadIcon />
                Download for Windows
              </a>
              <Link href="/connect" className="btn btn-ghost">
                Connect a machine →
              </Link>
            </div>
            <p className="mt-3 font-mono text-xs text-faint">
              Windows 10 / 11 · free · installs like an app, no account needed
            </p>
            <dl className="mt-12 grid max-w-md grid-cols-3 gap-6 border-t border-line pt-6">
              <Stat value="92%" label="less pen travel" />
              <Stat value="352" label="tracks parsed" />
              <Stat value="KiCad 10" label="native parser" />
            </dl>
          </div>

          {/* instrument panel: the real labExam board */}
          <div className="panel ticked p-1.5">
            <div className="flex items-center justify-between border-b border-line px-3 py-2">
              <span className="tlabel">labExam.kicad_pcb</span>
              <span className="tlabel">front layer</span>
            </div>
            <div className="panel-2 aspect-[16/10] w-full p-4">
              <PcbBoard animate showBack className="h-full w-full" />
            </div>
            <div className="grid grid-cols-3 divide-x divide-line border-t border-line text-center">
              <Readout k="SIZE" v="101 × 34 mm" />
              <Readout k="NETS" v="32" />
              <Readout k="G-CODE" v="580 ln" />
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------- pipeline */}
      <section id="how" className="border-y border-line bg-panel">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-2xl">
            <span className="tlabel">How it works</span>
            <h2 className="mt-3 text-3xl tracking-tight text-ink">
              From KiCad file to finished plot in five steps.
            </h2>
            <p className="mt-4 text-ink-soft">
              Every step shows its work, so you can check the geometry and the
              actual G-code before a motor ever moves.
            </p>
          </div>
          <ol className="mt-12 grid gap-px overflow-hidden rounded border border-line bg-line md:grid-cols-5">
            {pipeline.map((s) => (
              <li key={s.key} className="bg-panel-2 p-5">
                <span className="font-mono text-2xl text-copper">{s.key}</span>
                <h3 className="mt-4 text-base text-ink">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  {s.detail}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* --------------------------------------------------------------- device */}
      <section id="device" className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid items-center gap-14 lg:grid-cols-2">
          <div className="order-2 lg:order-1">
            <div className="panel ticked mx-auto max-w-sm p-6">
              <span className="tlabel">Connect a machine</span>
              <div className="mt-4 rounded border border-line-strong bg-well p-4">
                <p className="tlabel mb-2">Serial port</p>
                <div className="flex items-center gap-2 font-mono text-xl tracking-wider text-ink">
                  <span className="text-copper">COM3</span>· CH340
                </div>
              </div>
              <div className="mt-4 space-y-2.5 font-mono text-xs text-muted">
                <Row k="controller" v="Arduino Uno" />
                <Row k="firmware" v="Grbl 1.1f · grbl_servo_z" />
                <Row k="link" v="USB · 115200 baud" />
                <Row k="status" v="connected" accent />
              </div>
              <div className="mt-5 flex items-center gap-2 border-t border-line pt-4">
                <span className="text-xs text-copper">
                  ▸ Plotter found on this PC
                </span>
              </div>
            </div>
          </div>
          <div className="order-1 lg:order-2">
            <span className="tlabel">One cable, no setup</span>
            <h2 className="mt-3 text-3xl tracking-tight text-ink">
              Plug in the plotter and connect.
            </h2>
            <p className="mt-4 text-ink-soft leading-relaxed">
              The Arduino hangs off a USB cable on this PC, the way Universal
              Gcode Sender works. TraceWorks finds the port, spots the CH340
              chip, and talks Grbl to it directly. There is no network, no
              device ID, and nothing to pair.
            </p>
            <ul className="mt-6 space-y-3">
              {[
                "Pick the port and press Connect. The last one is remembered.",
                "Jog, zero and watch the live position before you plot.",
                "No hardware yet? Connect to the built-in simulator.",
              ].map((t) => (
                <li key={t} className="flex gap-3 text-sm text-ink-soft">
                  <span className="mt-1.5 h-1.5 w-1.5 flex-none bg-copper" />
                  {t}
                </li>
              ))}
            </ul>
            <Link href="/connect" className="btn btn-primary mt-8">
              Connect a machine
            </Link>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- feature */}
      <section className="border-y border-line bg-panel">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="grid gap-px overflow-hidden rounded border border-line bg-line md:grid-cols-3">
            <Feature
              title="Toolpath preview"
              body="The preview comes from the G-code itself. Solid lines are where the pen draws, dashed lines are where it travels, so what you see is what gets sent."
            />
            <Feature
              title="Less wasted motion"
              body="Reordering the moves and flipping trace endpoints cut the pen-up travel on our test board from 4200 mm to 332 mm."
            />
            <Feature
              title="Dry-check first"
              body="Run the whole file through Grbl's check mode with no motion to catch a bad line before the pen ever touches paper."
            />
            <Feature
              title="Both sides"
              body="Front and back copper get their own colors. Plot one side, flip the board, and line up the other."
            />
            <Feature
              title="Over USB"
              body="G-code streams over the serial cable to the Arduino, and the controller acknowledges every line before the next one goes."
            />
            <Feature
              title="Per-machine settings"
              body="Bed size, pen-up and pen-down height, and feed rates are saved for each machine to match the grbl_servo_z firmware."
            />
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------- hardware */}
      <section id="hardware" className="mx-auto max-w-6xl px-6 py-24">
        <div className="max-w-2xl">
          <span className="tlabel">Bring your own machine</span>
          <h2 className="mt-3 text-3xl tracking-tight text-ink">
            Works with the plotter you already build.
          </h2>
          <p className="mt-4 text-ink-soft">
            We don&apos;t reinvent motion control. Grbl handles the real-time
            work: flash grbl_servo_z onto an Arduino Uno once, plug it in over
            USB, and connect.
          </p>
        </div>
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Arduino Uno + grbl_servo_z", "Grbl 1.1f at 115200 baud. CH340 clones work."],
            ["28BYJ-48 + ULN2003 × 2", "X on D5–D2, Y on A3–A0. 500 mm/min max."],
            ["SG90 servo on D10", "Lifts the pen on Z: down below 0, up at 0 and above."],
            ["External 5 V supply", "Powers the servo and drivers, ground shared with the Uno."],
          ].map(([t, b]) => (
            <div key={t} className="panel ticked p-5">
              <p className="font-mono text-sm text-ink">{t}</p>
              <p className="mt-2 text-sm leading-relaxed text-muted">{b}</p>
            </div>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------------- pricing */}
      <section id="pricing" className="border-t border-line bg-panel">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <div className="mx-auto max-w-2xl text-center">
            <span className="tlabel">Pricing</span>
            <h2 className="mt-3 text-3xl tracking-tight text-ink">
              Pay once for the machine you pair.
            </h2>
            <p className="mt-4 text-ink-soft">
              No monthly fee. One price per plotter unlocks the software for
              that machine, and it stays yours.
            </p>
          </div>

          <div className="mx-auto mt-12 grid max-w-3xl gap-6 md:grid-cols-[1fr_1.2fr]">
            {/* price card */}
            <div className="panel ticked flex flex-col justify-between p-7">
              <div>
                <span className="tlabel">Per machine</span>
                <p className="mt-4 flex items-baseline gap-2">
                  <span className="text-5xl tracking-tight text-ink">$29</span>
                  <span className="font-mono text-sm text-muted">
                    once
                  </span>
                </p>
                <p className="mt-2 text-sm text-muted">
                  Charged the first time you pair a plotter. Pair a second one
                  later and it&apos;s another $29 for that machine.
                </p>
              </div>
              <Link href="/connect" className="btn btn-copper mt-6 w-full">
                Pair a machine
              </Link>
            </div>

            {/* what you get */}
            <div className="panel p-7">
              <span className="tlabel">What that gets you</span>
              <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                {[
                  "Unlimited boards and plots",
                  "Toolpath preview and G-code",
                  "The no-motion dry check",
                  "USB and WiFi streaming",
                  "Saved machine settings",
                  "Free updates, no expiry",
                ].map((f) => (
                  <li
                    key={f}
                    className="flex gap-2.5 text-sm text-ink-soft"
                  >
                    <span className="mt-1.5 h-1.5 w-1.5 flex-none bg-copper" />
                    {f}
                  </li>
                ))}
              </ul>
              <p className="mt-6 border-t border-line pt-4 text-sm text-muted">
                Running a classroom or a shop with a lot of machines? Get in
                touch and we&apos;ll sort out a bulk price.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------------- cta */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <div className="panel ticked flex flex-col items-center justify-between gap-6 p-10 text-center md:flex-row md:text-left">
          <div>
            <h2 className="text-2xl tracking-tight text-ink">
              Turn a board into a plot.
            </h2>
            <p className="mt-2 text-ink-soft">
              Create an account and pair the demo machine in under a minute, or
              install the Windows app and plot without an account.
            </p>
          </div>
          <div className="flex flex-none flex-wrap justify-center gap-3">
            <a href={WINDOWS_DOWNLOAD_URL} className="btn btn-primary">
              <DownloadIcon />
              Download for Windows
            </a>
            <Link href="/signup" className="btn btn-copper">
              Get started
            </Link>
            <Link href="/login" className="btn btn-ghost">
              Sign in
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}

/* ------------------------------------------------------------------ atoms */

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden fill="none">
      <path d="M7 1.5v8M3.5 6 7 9.5 10.5 6M2 12.5h10" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <dt className="font-mono text-2xl text-ink">{value}</dt>
      <dd className="tlabel mt-1 !tracking-normal">{label}</dd>
    </div>
  );
}

function Readout({ k, v }: { k: string; v: string }) {
  return (
    <div className="px-2 py-2.5">
      <p className="tlabel !text-[0.6rem]">{k}</p>
      <p className="mt-0.5 font-mono text-sm text-ink">{v}</p>
    </div>
  );
}

function Row({ k, v, accent }: { k: string; v: string; accent?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-faint">{k}</span>
      <span className={accent ? "text-copper" : "text-ink-soft"}>{v}</span>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="bg-panel-2 p-6">
      <h3 className="font-mono text-sm text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
    </div>
  );
}

