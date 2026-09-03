"use client";

import { useEffect, useRef, useState } from "react";

/*
  Click-to-edit text. Renders `value` as a heading; clicking swaps in an input
  seeded with the current value. Enter saves (calls `onSave`), Esc or blur
  cancels. Empty input is rejected — it reverts to the previous value.
*/
export default function InlineEdit({
  value,
  onSave,
  className,
  ariaLabel = "Edit",
}: {
  value: string;
  onSave: (next: string) => Promise<void> | void;
  className?: string;
  ariaLabel?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(value);
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing, value]);

  async function commit() {
    const next = draft.trim();
    if (!next || next === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } catch {
      /* keep editing so the user can retry */
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        onBlur={() => setEditing(false)}
        className={`w-full max-w-md rounded border border-line-strong bg-panel-2 px-2 py-0.5 outline-none focus:border-copper disabled:opacity-50 ${className ?? ""}`}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      aria-label={ariaLabel}
      title="Click to rename"
      className={`group inline-flex items-center gap-2 text-left hover:text-copper ${className ?? ""}`}
    >
      {value}
      <svg
        width="13"
        height="13"
        viewBox="0 0 14 14"
        fill="none"
        className="flex-none opacity-0 transition-opacity group-hover:opacity-60"
      >
        <path
          d="M9.5 2.5l2 2L5 11l-2.5.5L3 9l6.5-6.5z"
          stroke="currentColor"
          strokeWidth="1.1"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
