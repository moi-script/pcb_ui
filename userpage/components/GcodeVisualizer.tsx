"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { parseGcode, type Segment } from "@/lib/gcode";

type Props = {
  gcode: string;
  className?: string;
};

/* UGS conventions: red X, green Y, blue Z, yellow tool cone. The path colours
 * come from the site theme so the panel doesn't read as a bolted-on demo. */
const COLOR = {
  draw: 0xc2571f, // --color-fcu
  travel: 0xc2b8a1, // --color-line-strong
  grid: 0xd8d0be, // --color-line
  gridEdge: 0xc2b8a1,
  axisX: 0xc0392b,
  axisY: 0x2f7d55,
  axisZ: 0x2c5f8c,
  cone: 0xe8b73a,
  bg: 0xfcfaf4, // --color-panel-2
};

/**
 * Is this segment actually laying down ink?
 *
 * `rapid` alone isn't enough. The generator plunges with `G1 Z0`, which is a
 * feed move but draws nothing — colouring those as drawing puts a vertical
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

function positions(segments: Segment[], draw: boolean) {
  const picked = segments.filter((s) => isDraw(s) === draw);
  const a = new Float32Array(picked.length * 6);
  picked.forEach((s, i) => {
    a.set([s.x1, s.y1, s.z1, s.x2, s.y2, s.z2], i * 6);
  });
  return a;
}

export default function GcodeVisualizer({ gcode, className }: Props) {
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
  const [progress, setProgress] = useState(1);

  // Imperative handles the animation loop pokes without re-running the effect.
  const api = useRef<{
    apply: (p: number) => void;
    resetView: () => void;
    setTravelVisible: (v: boolean) => void;
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

    // Tool marker: a cone with its tip at the tool position, pointing down.
    const coneH = Math.max(span * 0.06, 2);
    const coneGeom = new THREE.ConeGeometry(coneH * 0.35, coneH, 20);
    coneGeom.translate(0, coneH / 2, 0); // tip at the mesh origin
    coneGeom.rotateX(Math.PI / 2); // point down -Z
    const cone = new THREE.Mesh(
      coneGeom,
      new THREE.MeshLambertMaterial({ color: COLOR.cone }),
    );
    scene.add(cone);

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

    /** Place the cone and reveal the path up to `p` (0..1 by distance). */
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

      cone.position.set(
        s.x1 + (s.x2 - s.x1) * t,
        s.y1 + (s.y2 - s.y1) * t,
        s.z1 + (s.z2 - s.z1) * t,
      );

      // Reveal completed segments of each type. Two draw calls, whatever the
      // board size — no per-frame geometry rebuild.
      const doneBefore = i;
      const drawnDone = doneBefore > 0 ? drawnUpTo[doneBefore - 1] : 0;
      const rapidDone = doneBefore > 0 ? rapidUpTo[doneBefore - 1] : 0;
      const cur = isDraw(s);
      drawGeom.setDrawRange(0, (drawnDone + (cur ? 1 : 0)) * 2);
      travelGeom.setDrawRange(0, (rapidDone + (cur ? 0 : 1)) * 2);
    };

    api.current = {
      apply,
      resetView,
      setTravelVisible: (v: boolean) => {
        travelLines.visible = v;
      },
    };
    apply(progressRef.current);

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
      if (playingRef.current && timeline.total > 0) {
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
      coneGeom.dispose();
      axisGeoms.forEach((g) => g.dispose());
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      drawLines.material.dispose();
      travelLines.material.dispose();
      cone.material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [parsed, timeline]);

  useEffect(() => {
    api.current?.setTravelVisible(showTravel);
  }, [showTravel]);

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
        <span className="text-faint">drag to orbit · scroll to zoom</span>
      </div>
    </div>
  );
}
