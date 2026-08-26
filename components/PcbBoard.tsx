"use client";

import { useMemo } from "react";
import { board as sampleBoard, type Track } from "@/lib/board";

type Props = {
  /** tracks to render; defaults to the built-in labExam sample */
  tracks?: Track[];
  width?: number;
  height?: number;
  showFront?: boolean;
  showBack?: boolean;
  /** draw each trace on mount */
  animate?: boolean;
  /** dashed straight hops between traces, like the toolpath preview */
  toolpath?: boolean;
  className?: string;
};

const PAD = 3; // mm border

function len(t: Track) {
  return Math.hypot(t.x2 - t.x1, t.y2 - t.y1);
}

export default function PcbBoard({
  tracks: tracksIn,
  width: widthIn,
  height: heightIn,
  showFront = true,
  showBack = true,
  animate = false,
  toolpath = false,
  className,
}: Props) {
  const allTracks = tracksIn ?? sampleBoard.tracks;
  const width = widthIn ?? sampleBoard.width;
  const height = heightIn ?? sampleBoard.height;

  const tracks = useMemo(
    () =>
      allTracks.filter(
        (t) =>
          (t.layer === "F.Cu" && showFront) ||
          (t.layer === "B.Cu" && showBack)
      ),
    [allTracks, showFront, showBack]
  );

  // Straight hops between consecutive front traces — evokes pen-up travel.
  const hops = useMemo(() => {
    if (!toolpath) return [];
    const f = allTracks.filter((t) => t.layer === "F.Cu");
    const out: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (let i = 1; i < f.length; i++) {
      out.push({ x1: f[i - 1].x2, y1: f[i - 1].y2, x2: f[i].x1, y2: f[i].y1 });
    }
    return out;
  }, [allTracks, toolpath]);

  const vb = `${-PAD} ${-PAD} ${width + PAD * 2} ${height + PAD * 2}`;

  return (
    <svg
      viewBox={vb}
      className={className}
      preserveAspectRatio="xMidYMid meet"
      style={{ width: "100%", height: "100%", display: "block" }}
    >
      {/* board outline */}
      <rect
        x={-1.5}
        y={-1.5}
        width={width + 3}
        height={height + 3}
        fill="none"
        stroke="var(--color-line-strong)"
        strokeWidth={0.3}
        rx={1}
      />

      {toolpath &&
        hops.map((h, i) => (
          <line
            key={`h${i}`}
            x1={h.x1}
            y1={h.y1}
            x2={h.x2}
            y2={h.y2}
            stroke="var(--color-faint)"
            strokeWidth={0.12}
            strokeDasharray="0.6 0.6"
            opacity={0.5}
          />
        ))}

      {tracks.map((t, i) => {
        const l = len(t);
        const color = t.layer === "F.Cu" ? "var(--color-fcu)" : "var(--color-bcu)";
        const style = animate
          ? ({
              strokeDasharray: l,
              strokeDashoffset: l,
              animation: `trace-draw 0.9s ease forwards`,
              animationDelay: `${(i % 120) * 0.012}s`,
              // custom prop for keyframe fallback
              ["--len" as string]: l,
            } as React.CSSProperties)
          : undefined;
        return (
          <line
            key={i}
            x1={t.x1}
            y1={t.y1}
            x2={t.x2}
            y2={t.y2}
            stroke={color}
            strokeWidth={Math.max(t.w, 0.26)}
            strokeLinecap="round"
            opacity={t.layer === "B.Cu" ? 0.62 : 0.95}
            style={style}
          />
        );
      })}
    </svg>
  );
}
