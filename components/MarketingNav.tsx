import Link from "next/link";
import Logo from "./Logo";

export default function MarketingNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <nav className="hidden items-center gap-8 md:flex">
          <a href="#how" className="tlabel hover:text-ink transition-colors">
            Pipeline
          </a>
          <a href="#device" className="tlabel hover:text-ink transition-colors">
            Pairing
          </a>
          <a href="#hardware" className="tlabel hover:text-ink transition-colors">
            Hardware
          </a>
          <a href="#pricing" className="tlabel hover:text-ink transition-colors">
            Pricing
          </a>
        </nav>
        <div className="flex items-center gap-3">
          <Link href="/login" className="tlabel hover:text-ink transition-colors">
            Sign in
          </Link>
          <Link href="/signup" className="btn btn-copper">
            Get started
          </Link>
        </div>
      </div>
    </header>
  );
}
