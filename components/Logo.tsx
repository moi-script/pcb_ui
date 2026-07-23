import Link from "next/link";

export default function Logo({ mark = true }: { mark?: boolean }) {
  return (
    <Link href="/" className="inline-flex items-center gap-2.5 group">
      {mark && (
        <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
          {/* a routed node: pad -> trace -> pad, copper */}
          <line x1="3" y1="16" x2="9" y2="16" stroke="var(--color-copper)" strokeWidth="1.6" />
          <line x1="9" y1="16" x2="14" y2="6" stroke="var(--color-copper)" strokeWidth="1.6" />
          <line x1="14" y1="6" x2="19" y2="6" stroke="var(--color-copper)" strokeWidth="1.6" />
          <circle cx="3" cy="16" r="2.1" fill="none" stroke="var(--color-ink)" strokeWidth="1.4" />
          <circle cx="19" cy="6" r="2.1" fill="var(--color-copper)" />
        </svg>
      )}
      <span
        className="font-mono text-[0.95rem] tracking-tight text-ink"
        style={{ fontWeight: 600 }}
      >
        trace<span className="text-copper">works</span>
      </span>
    </Link>
  );
}
