"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

export default function Uploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [file, setFile] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  function pick(files: FileList | null) {
    if (files && files.length) setFile(files[0].name);
  }

  function openPicker() {
    inputRef.current?.click();
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
      // Only the empty card is click-to-browse. Once a file is loaded the card
      // is inert, so the action buttons below don't reopen the file picker.
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
          <p className="mt-1 max-w-md text-xs text-muted">
            Routing turns a board into a pen toolpath and G-code. This prototype
            doesn&apos;t parse your own file yet, so it opens a fully routed
            sample so you can see what the result looks like.
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                router.push("/dashboard/projects/labexam");
              }}
              className="btn btn-copper"
            >
              See a routed board
            </button>
            <button
              type="button"
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
