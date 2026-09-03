// Product mock domain. Numbers are grounded in the real pipeline:
// the labExam board yields 143 F.Cu tracks, travel optimization cut
// pen-up travel from 4200 mm to 332 mm (~92%), 580-line G-code.

export type JobStatus = "plotted" | "ready" | "generating" | "draft";

export type Project = {
  id: string;
  name: string;
  board: string;
  status: JobStatus;
  updated: string;
  layer: "F.Cu" | "B.Cu";
  tracks: number;
  nets: number;
  size: string; // mm
  gcodeLines: number;
  drawMoves: number;
  travelMoves: number;
  penUpBefore: number; // mm
  penUpAfter: number; // mm
  estMinutes: number;
};

export const projects: Project[] = [
  {
    id: "labexam",
    name: "labExam",
    board: "labExam.kicad_pcb",
    status: "ready",
    updated: "2026-07-23 14:10",
    layer: "F.Cu",
    tracks: 143,
    nets: 32,
    size: "101.0 × 34.1",
    gcodeLines: 580,
    drawMoves: 143,
    travelMoves: 144,
    penUpBefore: 4200,
    penUpAfter: 332,
    estMinutes: 11,
  },
  {
    id: "blink-shield",
    name: "Blink Shield",
    board: "blink_shield.kicad_pcb",
    status: "plotted",
    updated: "2026-07-21 09:02",
    layer: "F.Cu",
    tracks: 58,
    nets: 14,
    size: "48.3 × 40.0",
    gcodeLines: 236,
    drawMoves: 58,
    travelMoves: 59,
    penUpBefore: 1740,
    penUpAfter: 168,
    estMinutes: 4,
  },
  {
    id: "555-timer",
    name: "555 Astable",
    board: "ne555_astable.kicad_pcb",
    status: "draft",
    updated: "2026-07-19 17:44",
    layer: "F.Cu",
    tracks: 31,
    nets: 9,
    size: "35.6 × 28.0",
    gcodeLines: 130,
    drawMoves: 31,
    travelMoves: 32,
    penUpBefore: 980,
    penUpAfter: 121,
    estMinutes: 3,
  },
];

export function getProject(id: string): Project | undefined {
  return projects.find((p) => p.id === id);
}

export type Device = {
  id: string;
  alias: string;
  firmware: string;
  controller: string;
  connection: "USB" | "WiFi";
  port: string;
  bed: string; // mm
  status: "online" | "idle" | "offline";
  penUpZ: number;
  penDownZ: number;
  travelFeed: number;
  drawFeed: number;
};

export const device: Device = {
  id: "TW-3F9A-C210",
  alias: "Bench Plotter 01",
  firmware: "FluidNC 3.9.7",
  controller: "MKS DLC32 · ESP32",
  connection: "WiFi",
  port: "192.168.1.42",
  bed: "300 × 300",
  status: "online",
  penUpZ: 5,
  penDownZ: 0,
  travelFeed: 3000,
  drawFeed: 800,
};

// A short, representative slice of the emitted G-code.
export const gcodeSample = `G21              ; units = mm
G90              ; absolute positioning
G0 Z5            ; pen up
G0 X12.400 Y8.100 F3000
G1 Z0 F3000      ; pen down
G1 X31.900 Y8.100 F800
G0 Z5            ; pen up
G0 X31.900 Y21.550 F3000
G1 Z0 F3000
G1 X44.700 Y21.550 F800
G0 Z5
; ... 143 traces, travel-optimized ...
G0 X0 Y0         ; return home
M2               ; end`;

export type PipelineStage = {
  key: string;
  title: string;
  detail: string;
};

export const pipeline: PipelineStage[] = [
  {
    key: "01",
    title: "Read the board",
    detail:
      "Your KiCad file goes in and every copper track comes back as plain coordinates in millimetres. It handles the newer KiCad 10 files that a lot of other tools still can't open.",
  },
  {
    key: "02",
    title: "See it by layer",
    detail:
      "The board gets drawn out before anything moves. Front-copper traces are one color, back-copper another, so it's easy to spot a route that landed somewhere you didn't expect.",
  },
  {
    key: "03",
    title: "Tidy up the path",
    detail:
      "The pen spends most of its time in the air, hopping between traces. Reordering those hops took the wasted travel on our test board from 4200 mm down to 332 mm, so a plot finishes faster and looks cleaner.",
  },
  {
    key: "04",
    title: "Check the toolpath",
    detail:
      "The plan gets drawn back out from the G-code itself: solid lines where the pen draws, dashed where it lifts and moves. If a move is wrong, you notice here instead of on paper.",
  },
  {
    key: "05",
    title: "Send it to the plotter",
    detail:
      "Push the file over USB or WiFi to your FluidNC board. Each line waits for the controller to answer before the next one goes, and you can do a no-motion dry check first to make sure the whole file is accepted.",
  },
];
