"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import {
  parseGcode,
  penProgress,
  PEN_TRACK_START,
  type PenTrack,
  type Segment,
} from "@/lib/gcode";

type Props = {
  gcode: string;
  className?: string;
  /**
   * The last line the controller acknowledged, or null when no job is
   * running. Drives which segments render as drawn.
   *
   * Deliberately not used to place the pen: GRBL acknowledges a line when
   * it has parsed and QUEUED it, not when it has executed it, so this index
   * runs ahead of the machine — sometimes by a hundred moves.
   */
  liveIndex?: number | null;
  /** The machine's reported work position. Where the pen actually is. */
  penPos?: [number, number, number] | null;
};

/**
 * Progress 0..1 for "the controller has acknowledged through line N".
 *
 * Segments carry the cleaned-file line number they came from, and one line
 * can emit several segments (a G1 with X, Y and Z all changing). Take the
 * LAST segment of the acknowledged line, not the first, or the path lags a
 * segment behind the machine for the whole job.
 */
function progressForLine(
  segments: Segment[],
  ends: Float64Array,
  total: number,
  line: number
): number {
  if (segments.length === 0 || total === 0) return 0;
  if (line <= 0) return 0;

  let lo = 0;
  let hi = segments.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].line <= line) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found < 0) return 0;
  return ends[found] / total;
}

/* UGS conventions: red X, green Y, blue Z, and a tool marker at the pen tip.
 * The path colours come from the site theme so the panel doesn't read as a
 * bolted-on demo. */
const COLOR = {
  draw: 0xc2571f, // --color-fcu
  travel: 0xc2b8a1, // --color-line-strong
  grid: 0xd8d0be, // --color-line
  gridEdge: 0xc2b8a1,
  axisX: 0xc0392b,
  axisY: 0x2f7d55,
  axisZ: 0x2c5f8c,
  penBody: 0xe8b73a,
  penMetal: 0xb8ac90,
  penNib: 0x3a352a, // --color-ink-soft
  bg: 0xfcfaf4, // --color-panel-2
};

/**
 * Is this segment actually laying down ink?
 *
 * `rapid` alone isn't enough. The generator plunges with a `G1 Z` move, which
 * is a feed move but draws nothing — colouring those as drawing puts a vertical
 * copper spike over every trace. Ink needs a feed move that travels in XY.
 */
function isDraw(s: Segment): boolean {
  return !s.rapid && (s.x1 !== s.x2 || s.y1 !== s.y2);
}

/** Cumulative 3D length up to the end of each segment, plus per-type counts. */
function buildTimeline(segments: Segment[]) {
  const ends = new Float64Array(segments.length);
  const drawnUpTo = new Int32Array(segments.length);
  const rapidUpTo = new Int32Array(segments.length);
  let total = 0;
  let drawn = 0;
  let rapid = 0;
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    total += Math.hypot(s.x2 - s.x1, s.y2 - s.y1, s.z2 - s.z1);
    ends[i] = total;
    if (isDraw(s)) drawn++;
    else rapid++;
    drawnUpTo[i] = drawn;
    rapidUpTo[i] = rapid;
  }
  return { ends, drawnUpTo, rapidUpTo, total };
}

/**
 * Display height for a G-code Z, as 0 (down) or 1 (up).
 *
 * The firmware reads Z as a flag, not a height: grbl_servo_z drops the pen
 * below zero and lifts it at or above. The real lift is the servo's own
 * mechanical throw, and the emitted numbers are ±0.5 mm — under a pixel on a
 * 100 mm board. So the scene keeps pen state in unit Z and the lift height is
 * applied as a scale, which makes it adjustable without touching a vertex or
 * reinterpreting the file.
 */
function unitZ(z: number): number {
  return z >= 0 ? 1 : 0;
}

function positions(segments: Segment[], draw: boolean) {
  const picked = segments.filter((s) => isDraw(s) === draw);
  const a = new Float32Array(picked.length * 6);
  picked.forEach((s, i) => {
    a.set(
      [s.x1, s.y1, unitZ(s.z1), s.x2, s.y2, unitZ(s.z2)],
      i * 6,
    );
  });
  return a;
}

/**
 * A pen, tip at the group origin, body running up +Z.
 *
 * The tip is the tool point, so the origin is what gets placed on the
 * toolpath — everything else hangs off it.
 */
function buildPen(length: number) {
  const g = new THREE.Group();
  const r = length * 0.075; // barrel radius
  const parts: THREE.BufferGeometry[] = [];

  const add = (
    geom: THREE.BufferGeometry,
    material: THREE.Material,
    y: number,
  ) => {
    const m = new THREE.Mesh(geom, material);
    m.position.y = y; // built along +Y, rotated to +Z below
    g.add(m);
    parts.push(geom);
    return m;
  };

  const body = new THREE.MeshLambertMaterial({ color: COLOR.penBody });
  const metal = new THREE.MeshLambertMaterial({ color: COLOR.penMetal });
  const nib = new THREE.MeshLambertMaterial({ color: COLOR.penNib });

  const nibH = length * 0.1;
  const gripH = length * 0.22;
  const barrelH = length * 0.68;

  // Point down, at the work. ConeGeometry puts its apex at +Y, which is
  // away from the paper here — the pen would meet the line with its blunt
  // end. A cylinder tapering to zero at -Y is the same shape the right way
  // up, so the sharpest part of the pen is the part touching the toolpath.
  add(new THREE.CylinderGeometry(r * 0.42, 0, nibH, 16), nib, nibH / 2);
  add(
    new THREE.CylinderGeometry(r * 0.92, r * 0.42, gripH, 20),
    body,
    nibH + gripH / 2,
  );
  add(
    new THREE.CylinderGeometry(r, r, length * 0.05, 20),
    metal,
    nibH + gripH + length * 0.025,
  );
  add(
    new THREE.CylinderGeometry(r, r * 0.92, barrelH, 20),
    body,
    nibH + gripH + barrelH / 2,
  );

  // Pocket clip down the side of the barrel.
  const clipH = barrelH * 0.55;
  const clip = add(
    new THREE.BoxGeometry(r * 0.44, clipH, r * 0.3),
    metal,
    nibH + gripH + barrelH * 0.72,
  );
  clip.position.z = r * 1.05;

  g.rotation.x = Math.PI / 2; // +Y body becomes +Z, tip stays at the origin
  return { pen: g, geometries: parts };
}

export default function GcodeVisualizer({
  gcode,
  className,
  liveIndex = null,
  penPos = null,
}: Props) {
  // A live job owns the timeline; the scrubber would only fight it.
  const following = liveIndex != null;
  const parsed = useMemo(() => parseGcode(gcode), [gcode]);
  const timeline = useMemo(() => buildTimeline(parsed.segments), [parsed]);

  const mountRef = useRef<HTMLDivElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  // Off by default, like the Travel toggle on the 2D preview above: on a dense
  // fill board the pen-up lifts are a wall of verticals that hide the drawing.
  const [showTravel, setShowTravel] = useState(false);
  // 0..1 through the job by distance. Kept in a ref for the animation loop and
  // mirrored into state for the slider, so rAF never waits on a React render.
  const progressRef = useRef(1);
  // Read inside the animation loop, which is set up once and must not close
  // over a stale `following`.
  const followingRef = useRef(false);
  followingRef.current = following;
  const [progress, setProgress] = useState(1);
  // How high a pen-up reads in the scene, in mm. A view setting only: the
  // G-code says ±0.5 mm because that is what the firmware wants, and the
  // servo's real throw is mechanical. 0 until the scene sizes it to the board.
  const liftRef = useRef(0);
  const [lift, setLiftState] = useState(0);
  const [maxLift, setMaxLift] = useState(0);

  // Imperative handles the animation loop pokes without re-running the effect.
  const api = useRef<{
    apply: (p: number) => void;
    resetView: () => void;
    setLift: (mm: number) => void;
    defaultLift: number;
    setTravelVisible: (v: boolean) => void;
    setPenPos: (pos: [number, number, number] | null) => void;
    progressAtPen: (
      pos: [number, number, number],
      ceiling: number
    ) => number;
  } | null>(null);

  const playingRef = useRef(playing);
  playingRef.current = playing;
  const speedRef = useRef(speed);
  speedRef.current = speed;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const { segments, bounds } = parsed;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(COLOR.bg);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    // Z-up, like every CNC control. Three defaults to Y-up.
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    camera.up.set(0, 0, 1);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    // Frame on the drawing, not on every point the tool visits: files
    // typically end with a rapid home to X0 Y0, and letting that into the
    // camera bounds pushes the actual work into a corner.
    const drawn = segments.filter(isDraw);
    const framed = drawn.length ? drawn : segments;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const s of framed) {
      minX = Math.min(minX, s.x1, s.x2);
      maxX = Math.max(maxX, s.x1, s.x2);
      minY = Math.min(minY, s.y1, s.y2);
      maxY = Math.max(maxY, s.y1, s.y2);
    }
    if (!Number.isFinite(minX)) {
      minX = 0;
      maxX = 100;
      minY = 0;
      maxY = 100;
    }
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const span = Math.max(maxX - minX, maxY - minY, 1);
    // Big enough to read at a glance without the lifts dwarfing the drawing.
    const defaultLift = Math.max(span * 0.05, 2);

    // Bed grid, 10 mm cells, anchored at the machine origin like a real bed
    // and stretched to cover the work wherever it sits on it.
    const reach = Math.max(maxX, maxY, bounds?.maxX ?? 0, bounds?.maxY ?? 0, 10);
    const bed = Math.ceil((reach * 1.1) / 10) * 10;
    const grid = new THREE.GridHelper(bed, bed / 10, COLOR.gridEdge, COLOR.grid);
    grid.rotation.x = Math.PI / 2; // GridHelper lies in XZ; put it in XY
    grid.position.set(bed / 2, bed / 2, 0);
    scene.add(grid);

    const axis = (
      from: [number, number, number],
      to: [number, number, number],
      color: number,
    ) => {
      const g = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(...from),
        new THREE.Vector3(...to),
      ]);
      scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color })));
      return g;
    };
    const axisGeoms = [
      axis([0, 0, 0], [bed, 0, 0], COLOR.axisX),
      axis([0, 0, 0], [0, bed, 0], COLOR.axisY),
      axis([0, 0, 0], [0, 0, span * 0.2], COLOR.axisZ),
    ];

    const drawGeom = new THREE.BufferGeometry();
    drawGeom.setAttribute(
      "position",
      new THREE.BufferAttribute(positions(segments, true), 3),
    );
    const drawLines = new THREE.LineSegments(
      drawGeom,
      new THREE.LineBasicMaterial({ color: COLOR.draw }),
    );
    scene.add(drawLines);

    const travelGeom = new THREE.BufferGeometry();
    travelGeom.setAttribute(
      "position",
      new THREE.BufferAttribute(positions(segments, false), 3),
    );
    const travelLines = new THREE.LineSegments(
      travelGeom,
      new THREE.LineBasicMaterial({
        color: COLOR.travel,
        transparent: true,
        opacity: 0.75,
      }),
    );
    scene.add(travelLines);

    const { pen, geometries: penGeoms } = buildPen(
      Math.max(span * 0.16, 6),
    );
    scene.add(pen);

    scene.add(new THREE.AmbientLight(0xffffff, 1.7));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(1, -1, 2);
    scene.add(key);

    const resetView = () => {
      camera.position.set(cx - span * 0.35, cy - span * 0.95, span * 0.85);
      controls.target.set(cx, cy, 0);
      controls.update();
    };
    resetView();

    /**
     * Display lift, in mm. Pen state lives in the scene as unit Z, so raising
     * or lowering the pen-up height is a scale on the line sets and a factor
     * on the pen's own Z — no vertex is touched and the parsed G-code is
     * untouched either.
     */
    let lift = liftRef.current;
    const setLift = (mm: number) => {
      lift = mm;
      drawLines.scale.z = mm;
      travelLines.scale.z = mm;
      apply(progressRef.current);
    };

    // Where the machine reports its pen, when anything is reporting.
    let penOverride: [number, number, number] | null = null;

    /** Place the pen and reveal the path up to `p` (0..1 by distance). */
    const apply = (p: number) => {
      const { ends, drawnUpTo, rapidUpTo, total } = timeline;
      if (!segments.length || total === 0) {
        drawGeom.setDrawRange(0, 0);
        travelGeom.setDrawRange(0, 0);
        return;
      }
      const target = p * total;

      // Which segment are we inside? Binary search the cumulative lengths.
      let lo = 0;
      let hi = ends.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (ends[mid] < target) lo = mid + 1;
        else hi = mid;
      }
      const i = lo;
      const s = segments[i];
      const segStart = i === 0 ? 0 : ends[i - 1];
      const segLen = ends[i] - segStart;
      const t = segLen > 0 ? Math.min((target - segStart) / segLen, 1) : 1;

      // The pen goes where the machine says it is when we are being told;
      // the interpolated scrub point is a guess that runs ahead of it.
      if (penOverride) {
        pen.position.set(
          penOverride[0],
          penOverride[1],
          unitZ(penOverride[2]) * lift,
        );
      } else {
        // Interpolating unit Z means the pen visibly rises and falls across a
        // Z move rather than teleporting between the two states.
        const uz = unitZ(s.z1) + (unitZ(s.z2) - unitZ(s.z1)) * t;
        pen.position.set(
          s.x1 + (s.x2 - s.x1) * t,
          s.y1 + (s.y2 - s.y1) * t,
          uz * lift,
        );
      }

      // Reveal completed segments of each type. Two draw calls, whatever the
      // board size — no per-frame geometry rebuild.
      const doneBefore = i;
      const drawnDone = doneBefore > 0 ? drawnUpTo[doneBefore - 1] : 0;
      const rapidDone = doneBefore > 0 ? rapidUpTo[doneBefore - 1] : 0;
      const cur = isDraw(s);
      drawGeom.setDrawRange(0, (drawnDone + (cur ? 1 : 0)) * 2);
      travelGeom.setDrawRange(0, (rapidDone + (cur ? 0 : 1)) * 2);
    };

    // How far along the path the pen has been matched to. Monotone on
    // purpose: a toolpath crosses itself constantly, and a match free to
    // jump backwards would rub the drawn line out wherever the machine
    // passes near somewhere it has already been. The matching itself lives
    // in lib/gcode so it can be tested without a scene.
    let penTrack: PenTrack = PEN_TRACK_START;

    const progressAtPen = (
      pos: [number, number, number],
      ceiling: number,
    ): number => {
      penTrack = penProgress(
        segments,
        timeline.ends,
        timeline.total,
        pos,
        ceiling,
        penTrack,
      );
      return penTrack.progress;
    };

    api.current = {
      apply,
      resetView,
      progressAtPen,
      setLift,
      defaultLift,
      setPenPos: (pos: [number, number, number] | null) => {
        penOverride = pos;
        apply(progressRef.current);
      },
      setTravelVisible: (v: boolean) => {
        travelLines.visible = v;
      },
    };
    const initial = liftRef.current || defaultLift;
    liftRef.current = initial;
    setLift(initial);
    setLiftState(initial);
    setMaxLift(Math.max(span * 0.25, 10));

    const resize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(mount);

    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (playingRef.current && !followingRef.current && timeline.total > 0) {
        // 120 mm/s at 1x — fast enough to watch a board finish, slow enough
        // to follow the pen.
        const step = (120 * speedRef.current * dt) / timeline.total;
        let p = progressRef.current + step;
        if (p >= 1) {
          p = 1;
          setPlaying(false);
        }
        progressRef.current = p;
        setProgress(p);
        apply(p);
      }
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      api.current = null;
      controls.dispose();
      drawGeom.dispose();
      travelGeom.dispose();
      penGeoms.forEach((g) => g.dispose());
      axisGeoms.forEach((g) => g.dispose());
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      drawLines.material.dispose();
      travelLines.material.dispose();
      pen.children.forEach((c) => {
        const m = (c as THREE.Mesh).material as THREE.Material;
        m.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [parsed, timeline]);

  useEffect(() => {
    api.current?.setTravelVisible(showTravel);
  }, [showTravel]);

  // One effect, not two: the pen override has to be in place before the
  // path is revealed, or a frame renders the pen at the old position.
  useEffect(() => {
    if (!api.current) return;
    if (liveIndex == null) {
      api.current.setPenPos(penPos);
      return;
    }
    const ceiling = progressForLine(
      parsed.segments,
      timeline.ends,
      timeline.total,
      liveIndex
    );
    // Follow the pen where the machine reports one, and fall back to the
    // acknowledged count only when it does not — otherwise the drawn line
    // runs ahead of the machine by however much the controller has queued.
    const p = penPos ? api.current.progressAtPen(penPos, ceiling) : ceiling;
    progressRef.current = p;
    setProgress(p);
    api.current.setPenPos(penPos); // applies at the new progress
  }, [liveIndex, penPos, parsed, timeline]);

  const scrub = (p: number) => {
    progressRef.current = p;
    setProgress(p);
    api.current?.apply(p);
  };

  const drawn = parsed.segments.filter(isDraw).length;
  const rapids = parsed.segments.length - drawn;

  if (!parsed.segments.length) {
    return (
      <div className={className}>
        <div className="flex h-full items-center justify-center font-mono text-xs text-faint">
          No movement in this G-code.
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        {/* A scrubber that fights a live feed is a control that does nothing
            you can see, so while a job is running it is replaced by what the
            machine is actually reporting. */}
        {following ? (
          <>
            <span className="tlabel flex items-center gap-2 !text-copper">
              <span className="dot dot-live" />
              live
            </span>
            <div className="h-1 min-w-40 flex-1 bg-line">
              <div
                className="h-full bg-copper"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
            <span className="w-10 text-right font-mono text-xs text-muted">
              {Math.round(progress * 100)}%
            </span>
          </>
        ) : (
          <>
            <button
              onClick={() => {
                if (progressRef.current >= 1) scrub(0);
                setPlaying((v) => !v);
              }}
              className="tlabel w-16 text-left hover:text-copper"
            >
              {playing ? "❚❚ pause" : progress >= 1 ? "↻ replay" : "▶ play"}
            </button>

            <input
              type="range"
              min={0}
              max={1000}
              value={Math.round(progress * 1000)}
              onChange={(e) => {
                setPlaying(false);
                scrub(Number(e.target.value) / 1000);
              }}
              aria-label="Scrub toolpath"
              className="h-1 min-w-40 flex-1 cursor-pointer accent-copper"
            />

            <span className="w-10 text-right font-mono text-xs text-muted">
              {Math.round(progress * 100)}%
            </span>

            <label className="flex items-center gap-1.5 font-mono text-xs text-muted">
              <span className="text-faint">speed</span>
              <select
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
                className="border border-line bg-panel-2 px-1 py-0.5"
                aria-label="Playback speed"
              >
                {[0.25, 0.5, 1, 2, 4, 8].map((s) => (
                  <option key={s} value={s}>
                    {s}×
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        <label
          className="flex items-center gap-1.5 font-mono text-xs text-muted"
          title={
            "How high a pen-up is drawn, for looking at only. The G-code keeps " +
            "the ±0.5 mm the firmware needs — pen state is the sign of Z, " +
            "and the real lift is the servo's own throw."
          }
        >
          <span className="text-faint">lift</span>
          <input
            type="range"
            min={0}
            max={Math.max(Math.round(maxLift * 10), 10)}
            value={Math.round(lift * 10)}
            onChange={(e) => {
              const mm = Number(e.target.value) / 10;
              liftRef.current = mm;
              setLiftState(mm);
              api.current?.setLift(mm);
            }}
            aria-label="Pen-up height shown (view only)"
            className="h-1 w-20 cursor-pointer accent-copper"
          />
          <span className="w-12 text-right">{lift.toFixed(1)} mm</span>
        </label>

        <button
          onClick={() => setShowTravel((v) => !v)}
          className="tlabel hover:text-copper"
          aria-pressed={showTravel}
        >
          {showTravel ? "hide travel" : "show travel"}
        </button>

        <button
          onClick={() => api.current?.resetView()}
          className="tlabel hover:text-copper"
        >
          reset view
        </button>
      </div>

      <div ref={mountRef} className="h-[26rem] w-full cursor-grab" />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line px-4 py-2.5 font-mono text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-fcu" /> {drawn} pen-down (drawing)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-line-strong" /> {rapids}{" "}
          pen-up
        </span>
        <span className="text-faint">
          drag to orbit · scroll to zoom · lift is a view setting, not the
          G-code
        </span>
      </div>
    </div>
  );
}
