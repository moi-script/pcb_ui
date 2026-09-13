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
      "Push the file over USB to your Arduino running grbl_servo_z. Each line waits for the controller to answer before the next one goes, and you can do a no-motion dry check first to make sure the whole file is accepted.",
  },
];
