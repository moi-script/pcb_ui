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

  // An image gets traced instead of routed, and tracing needs to be told how
  // big the result should be — an image has pixels, the machine has mm.
  const isImage = !!file && file.type.startsWith("image/");
  const [sizeMm, setSizeMm] = useState(50);
  const [mode, setMode] = useState<"centerline" | "outline">("centerline");
  const [preset, setPreset] = useState<"line" | "pcb">("line");
  const [invert, setInvert] = useState(false);

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
      const board = isImage
        ? await api.trace(file, session.email, {
            size_mm: sizeMm,
            mode,
            preset,
            threshold: null,
            invert,
          })
        : await api.route(file, session.email);
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
        accept=".kicad_pcb,.pcb,.pro,image/png,image/jpeg,image/bmp,image/webp"
        className="hidden"
        onChange={(e) => pick(e.target.files)}
      />

      <UploadIcon />

      {file ? (
        <>
          <p className="mt-3 font-mono text-sm text-ink">{file.name}</p>
          <p className="mt-1 max-w-md text-xs text-muted">
            {isImage
              ? "Tracing finds the centre of every line in the image and turns it into a pen path, then saves the result to your account."
              : "Routing reads the board, plans the pen path, and generates the G-code on the server, then saves the result to your account."}
          </p>

          {isImage && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="mt-4 w-full max-w-md rounded border border-line bg-panel-2 p-3 text-left"
            >
              <span className="tlabel">trace options</span>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="tlabel">longest edge (mm)</span>
                  <input
                    type="number"
                    min={1}
                    max={300}
                    value={sizeMm}
                    onChange={(e) => setSizeMm(Number(e.target.value))}
                    className="field mt-1 w-full"
                  />
                </label>
                <label className="block">
                  <span className="tlabel">source</span>
                  <select
                    value={preset}
                    onChange={(e) =>
                      setPreset(e.target.value as "line" | "pcb")
                    }
                    className="field mt-1 w-full"
                  >
                    <option value="line">Line art</option>
                    <option value="pcb">PCB photo</option>
                  </select>
                </label>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="tlabel">trace mode</span>
                  <select
                    value={mode}
                    onChange={(e) =>
                      setMode(e.target.value as "centerline" | "outline")
                    }
                    className="field mt-1 w-full"
                  >
                    <option value="centerline">Centreline</option>
                    <option value="outline">Outline</option>
                  </select>
                </label>
                <label className="mt-5 flex items-center gap-2 text-sm text-ink-soft">
                  <input
                    type="checkbox"
                    checked={invert}
                    onChange={(e) => setInvert(e.target.checked)}
                  />
                  Light lines on dark
                </label>
              </div>
              <p className="mt-3 text-xs text-muted">
                Centreline draws one line down the middle of each stroke.
                Outline draws around each shape — pick it for etch resist,
                where a centreline would leave a wide trace only partly
                covered.
              </p>
            </div>
          )}

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
              {isImage
                ? busy
                  ? "Tracing…"
                  : "Trace this image"
                : busy
                  ? "Routing…"
                  : "Route this board"}
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
            Drop a <span className="font-mono text-copper">.kicad_pcb</span> to
            route it, or an image to trace it
          </p>
          <p className="mt-1 text-xs text-muted">
            Single-layer boards · KiCad 10 parser · PNG/JPG centreline tracing
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
