"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

export default function Uploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const { session } = useAuth();

  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pick(files: FileList | null) {
    if (files && files.length) {
      setFile(files[0]);
      setError(null);
    }
  }

  function openPicker() {
    inputRef.current?.click();
  }

  async function routeFile() {
    if (!file || !session) return;
    setBusy(true);
    setError(null);
    try {
      const board = await api.route(file, session.email);
      router.push(`/dashboard/projects/${board.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        pick(e.dataTransfer.files);
      }}
      onClick={file ? undefined : openPicker}
      role={file ? undefined : "button"}
      tabIndex={file ? undefined : 0}
      onKeyDown={(e) => {
        if (!file && (e.key === "Enter" || e.key === " ")) openPicker();
      }}
      className={`flex flex-col items-center justify-center rounded border border-dashed px-6 py-10 text-center transition-colors ${
        file ? "cursor-default" : "cursor-pointer"
      } ${
        drag
          ? "border-copper bg-panel-2"
          : "border-line-strong bg-panel hover:border-copper hover:bg-panel-2"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".kicad_pcb,.pcb,.pro"
        className="hidden"
        onChange={(e) => pick(e.target.files)}
      />

      <UploadIcon />

      {file ? (
        <>
          <p className="mt-3 font-mono text-sm text-ink">{file.name}</p>
          <p className="mt-1 max-w-md text-xs text-muted">
            Routing reads the board, plans the pen path, and generates the
            G-code on the server, then saves the result to your account.
          </p>

          {error && (
            <p className="mt-3 max-w-md text-sm text-danger">{error}</p>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                routeFile();
              }}
              className="btn btn-copper"
            >
              {busy ? "Routing…" : "Route this board"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                openPicker();
              }}
              className="btn btn-ghost"
            >
              Choose another file
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="mt-3 text-sm text-ink">
            Drop a <span className="font-mono text-copper">.kicad_pcb</span> file
            to route it
          </p>
          <p className="mt-1 text-xs text-muted">
            Single-layer boards · KiCad 10 parser · coordinates in mm
          </p>
          <span className="btn btn-ghost mt-4">Browse files</span>
        </>
      )}
    </div>
  );
}

function UploadIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 16V4m0 0L7 9m5-5l5 5M4 20h16"
        stroke="var(--color-copper)"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
