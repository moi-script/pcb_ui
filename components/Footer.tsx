import Logo from "./Logo";

export default function Footer() {
  return (
    <footer className="border-t border-line bg-panel">
      <div className="mx-auto max-w-6xl px-6 py-14">
        <div className="flex flex-col justify-between gap-8 md:flex-row">
          <div className="max-w-xs">
            <Logo />
            <p className="mt-4 text-sm leading-relaxed text-muted">
              A browser workbench for single-layer PCB pen plotting. Built for
              makers and students, not copper milling.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-12 sm:grid-cols-3">
            <FooterCol
              title="Product"
              links={["Pipeline", "Device pairing", "Hardware", "Pricing"]}
            />
            <FooterCol
              title="Build"
              links={["FluidNC", "MKS DLC32", "ESP32 setup", "G-code reference"]}
            />
            <FooterCol
              title="Account"
              links={["Sign in", "Create account", "Pair a device"]}
            />
          </div>
        </div>
        <div className="mt-12 flex flex-col justify-between gap-3 border-t border-line pt-6 text-xs text-faint sm:flex-row">
          <span className="font-mono">© 2026 TraceWorks · v0.1</span>
          <span className="font-mono">
            Motion control by FluidNC · not affiliated
          </span>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: string[] }) {
  return (
    <div>
      <p className="tlabel mb-3">{title}</p>
      <ul className="space-y-2">
        {links.map((l) => (
          <li key={l}>
            <span className="text-sm text-ink-soft hover:text-copper transition-colors cursor-pointer">
              {l}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
