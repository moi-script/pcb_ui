/**
 * G-code parser for the toolpath visualizer.
 *
 * A modal state machine: it walks the file line by line, tracks where the tool
 * is, and emits one segment per move. Deliberately narrow — it understands the
 * subset `pcb_gcode.py` and the tracer emit (G0/G1, G90/G91, G20/G21) and
 * ignores everything else rather than guessing.
 *
 * Pure: no DOM, no Three.js. The renderer consumes `Segment[]`.
 */

export type Segment = {
  x1: number;
  y1: number;
  z1: number;
  x2: number;
  y2: number;
  z2: number;
  /** true for G0 (pen-up travel), false for G1 (pen-down drawing) */
  rapid: boolean;
  /**
   * 1-based index of the source line in the CLEANED line list — comments and
   * blanks stripped, exactly as serverside/job.py's load_lines() counts them.
   * The backend reports progress as a count of those lines, so anything else
   * here would drift by however many comments the file happens to carry.
   */
  line: number;
};

export type Bounds = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
};

export type ParsedGcode = {
  segments: Segment[];
  /** null when nothing moved — an empty file has no extent */
  bounds: Bounds | null;
  /** total mm of G1 motion */
  drawLength: number;
  /** total mm of G0 motion */
  travelLength: number;
};

const MM_PER_INCH = 25.4;

/**
 * The line as serverside/job.py's load_lines() would keep it: `;` to
 * end-of-line removed, then trimmed. Empty means the backend drops it and
 * never counts it, so neither may we.
 *
 * Deliberately NOT the same as `decomment` below, which also strips `( ... )`
 * for parsing. A parenthesised-only line still costs the backend a line
 * number, and stamping segments with anything else would drift the live
 * progress by however many such lines the file carries.
 */
function keptByBackend(raw: string): string {
  return raw.split(";", 1)[0].trim();
}

/** Strip `;` to end-of-line and `( ... )` comments. */
function decomment(line: string): string {
  return line.replace(/\([^)]*\)/g, " ").split(";", 1)[0];
}

/**
 * Pull every `<letter><number>` word out of a line.
 *
 * Loose on purpose: real files come unspaced (`g1x10y20`) and lowercase, and
 * numbers show up as `-1.5`, `.25`, `+3`, or `1e2`.
 */
function words(line: string): [string, number][] {
  const out: [string, number][] = [];
  const re = /([A-Za-z])\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) out.push([m[1].toUpperCase(), Number(m[2])]);
  return out;
}

export function parseGcode(text: string): ParsedGcode {
  const segments: Segment[] = [];

  let x = 0;
  let y = 0;
  let z = 0;
  let scale = 1; // G20 switches this to 25.4
  let absolute = true; // G90 / G91
  let motion: 0 | 1 | null = null; // last G0/G1; null until one is seen

  let drawLength = 0;
  let travelLength = 0;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  let moved = false;

  const visit = (px: number, py: number, pz: number) => {
    if (px < minX) minX = px;
    if (px > maxX) maxX = px;
    if (py < minY) minY = py;
    if (py > maxY) maxY = py;
    if (pz < minZ) minZ = pz;
    if (pz > maxZ) maxZ = pz;
  };

  let lineNo = 0;

  for (const raw of text.split(/\r?\n/)) {
    // Counted before any parser-side skipping, so the number stays in step
    // with the backend even on lines this parser ignores ($C, M3, G4, …).
    if (keptByBackend(raw)) lineNo += 1;

    const line = decomment(raw);
    if (!line.trim()) continue;

    const ws = words(line);

    // Modal settings first: they apply to coordinates on the same line.
    let motionThisLine: 0 | 1 | null = null;
    let unsupportedMotion = false;
    for (const [letter, value] of ws) {
      if (letter !== "G") continue;
      if (value === 0 || value === 1) motionThisLine = value as 0 | 1;
      else if (value === 20) scale = MM_PER_INCH;
      else if (value === 21) scale = 1;
      else if (value === 90) absolute = true;
      else if (value === 91) absolute = false;
      // Anything else (G2/G3 arcs, G4 dwell, G28 home) is a motion code we
      // will not fake. Mark it so the line's coordinates are not read as a
      // straight line the machine never travels.
      else unsupportedMotion = true;
    }
    if (motionThisLine !== null) motion = motionThisLine;
    if (unsupportedMotion && motionThisLine === null) continue;

    // Then the destination.
    let nx = x;
    let ny = y;
    let nz = z;
    let hasAxis = false;
    for (const [letter, value] of ws) {
      const mm = value * scale;
      if (letter === "X") {
        nx = absolute ? mm : x + mm;
        hasAxis = true;
      } else if (letter === "Y") {
        ny = absolute ? mm : y + mm;
        hasAxis = true;
      } else if (letter === "Z") {
        nz = absolute ? mm : z + mm;
        hasAxis = true;
      }
    }

    if (!hasAxis || motion === null) continue;
    if (nx === x && ny === y && nz === z) continue; // move to nowhere

    if (!moved) {
      visit(x, y, z);
      moved = true;
    }
    visit(nx, ny, nz);

    const length = Math.hypot(nx - x, ny - y, nz - z);
    if (motion === 0) travelLength += length;
    else drawLength += length;

    segments.push({
      x1: x,
      y1: y,
      z1: z,
      x2: nx,
      y2: ny,
      z2: nz,
      rapid: motion === 0,
      line: lineNo,
    });

    x = nx;
    y = ny;
    z = nz;
  }

  return {
    segments,
    bounds: moved ? { minX, maxX, minY, maxY, minZ, maxZ } : null,
    drawLength,
    travelLength,
  };
}

/** The running match state. Hand the previous one back on every call. */
export type PenTrack = {
  /** 0..1 along the path, by distance. Never greater than the ceiling given. */
  progress: number;
  /** Where the search got to. */
  cursor: number;
};

export const PEN_TRACK_START: PenTrack = { progress: 0, cursor: 0 };

/**
 * Where on the toolpath the machine's reported position actually is.
 *
 * The obvious way to animate a running job — reveal the path up to the last
 * line the controller acknowledged — draws ahead of the machine, because
 * GRBL says `ok` when it has PARSED AND QUEUED a line, not when it has
 * executed it. On a board with any planner depth the line appears on screen
 * and the pen arrives seconds later.
 *
 * So the acknowledged point is used only as a `ceiling` — the pen cannot be
 * past what was never sent — and the reported position picks the point
 * beneath it, by projecting onto each candidate segment and taking the
 * nearest.
 *
 * The result is monotone, and that is not a detail. A toolpath crosses and
 * doubles back on itself constantly, so the nearest point to a reported
 * position is genuinely ambiguous: on an out-and-back trace, halfway home
 * is equidistant from somewhere the pen has already been. Left free, the
 * match would rewind and un-draw finished work every time. Three things
 * hold the line forward: the search starts at the previous cursor, ties go
 * to the later segment, and the answer is floored at the previous progress.
 * The floor lifts only when `ceiling` itself drops below it, which is a
 * restart — a new run of the same file, from the top.
 *
 * Matching is in XY only. Z on these files is a pen up/down flag, not a
 * height, so including it would drag every match towards whichever segments
 * happen to share the current pen state.
 */
export function penProgress(
  segments: Segment[],
  ends: Float64Array,
  total: number,
  pos: [number, number, number],
  ceiling: number,
  prev: PenTrack
): PenTrack {
  if (segments.length === 0 || total === 0) return PEN_TRACK_START;

  const clamped = ceiling < 0 ? 0 : ceiling > 1 ? 1 : ceiling;
  const target = clamped * total;

  // Segment index holding the ceiling.
  let lo = 0;
  let hi = ends.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ends[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const limit = lo;

  // The ceiling falling below where we had got to means the file went back
  // to the top: a restart. Nothing before it can be carried over.
  const restarted = clamped < prev.progress;
  const floor = restarted ? 0 : prev.progress;
  let from = restarted ? 0 : prev.cursor;
  if (from > limit || from < 0) from = 0;

  let bestIndex = -1;
  let bestDist = Infinity;
  let bestT = 0;
  for (let i = from; i <= limit; i++) {
    const s = segments[i];
    const dx = s.x2 - s.x1;
    const dy = s.y2 - s.y1;
    const len2 = dx * dx + dy * dy;
    // A pure Z move — the pen lifting — has no XY extent to project onto.
    let t = 0;
    if (len2 > 0) {
      t = ((pos[0] - s.x1) * dx + (pos[1] - s.y1) * dy) / len2;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
    }
    const px = s.x1 + dx * t;
    const py = s.y1 + dy * t;
    const d = (pos[0] - px) ** 2 + (pos[1] - py) ** 2;
    // `<=`, so an exact tie goes to the later segment — the machine is
    // moving forward through the file, not back.
    if (d <= bestDist) {
      bestDist = d;
      bestIndex = i;
      bestT = t;
    }
  }

  if (bestIndex < 0) return { progress: Math.min(clamped, floor), cursor: from };

  const segStart = bestIndex === 0 ? 0 : ends[bestIndex - 1];
  const segLen = ends[bestIndex] - segStart;
  const matched = (segStart + segLen * bestT) / total;
  const progress = Math.min(clamped, Math.max(floor, matched));
  return { progress, cursor: bestIndex };
}
