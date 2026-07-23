"use client";

import { useRef, useState } from "react";

export default function Uploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  function pick(files: FileList | null) {
    if (files && files.length) setFile(files[0].name);
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
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
      className={`flex cursor-pointer flex-col items-center justify-center rounded border border-dashed px-6 py-10 text-center transition-colors ${
        drag
          ? "border-copper bg-panel-2"
          : "border-line-strong bg-panel hover:border-copper hover:bg-panel-2"
      }`}
    >
      {/* the real file input — this is what opens the OS file manager */}
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
          <p className="mt-3 font-mono text-sm text-ink">{file}</p>
          <p className="mt-1 text-xs text-muted">
            ready to route. parsing runs on the server in this prototype.
          </p>
          <span className="btn btn-copper mt-4">Route this board</span>
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
