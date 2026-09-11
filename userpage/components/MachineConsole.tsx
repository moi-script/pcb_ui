"use client";

import { useEffect, useRef, useState } from "react";

import type { ConsoleLine } from "@/lib/api";

function tone(line: ConsoleLine): string {
  if (line.kind === "error" || line.kind === "alarm") return "text-warn";
  if (line.direction === "tx") return "text-copper";
  return "text-muted";
}

/**
 * What actually went down the wire, and a way to send one line yourself.
 *
 * Auto-scrolls only while the view is already at the bottom: yanking someone
 * back down while they are reading the error they scrolled up to find is how
 * a log becomes unusable exactly when it matters.
 */
export default function MachineConsole({
  lines,
  onSend,
  disabled,
  status,
  placeholder,
  label = "Console",
}: {
  lines: ConsoleLine[];
  onSend: (line: string) => void;
  disabled: boolean;
  /** Shown at the right of the header — who is on the wire, and where. */
  status?: React.ReactNode;
  /**
   * Replaces the input's placeholder. Worth setting wherever the field is
   * disabled for a reason other than a missing machine: "not connected" is
   * the wrong answer when the cable is fine and this view is simply
   * read-only.
   */
  placeholder?: string;
  /** Pass null where the surrounding section already names this. */
  label?: string | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    const el = box.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  function track() {
    const el = box.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  function send(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || disabled) return;
    onSend(text);
    setDraft("");
  }

  return (
    <div className="panel ticked flex min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
        {label && <span className="tlabel">{label}</span>}
        {status}
      </div>

      <div
        ref={box}
        onScroll={track}
        className="h-64 overflow-y-auto px-5 py-3 font-mono text-xs leading-relaxed"
      >
        {lines.length === 0 ? (
          <p className="text-faint">nothing sent yet</p>
        ) : (
          lines.map((l) => (
            <p key={l.seq} className={tone(l)}>
              <span className="text-faint">
                {l.direction === "tx" ? "› " : "‹ "}
              </span>
              {l.text}
            </p>
          ))
        )}
      </div>

      <form onSubmit={send} className="border-t border-line p-3">
        <input
          className="field font-mono text-xs"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            placeholder ?? (disabled ? "not connected" : "$$ or a G-code line")
          }
          disabled={disabled}
        />
      </form>
    </div>
  );
}
