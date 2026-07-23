// Real geometry extracted from labExam.kicad_pcb via pcb_read.py.
// 352 copper tracks (143 F.Cu + 209 B.Cu), 32 nets, ~101 x 34 mm.
import raw from "@/board_raw.json";

export type Track = {
  net: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  w: number;
  layer: "F.Cu" | "B.Cu";
};

export type Board = {
  width: number;
  height: number;
  fcu: number;
  bcu: number;
  nets: string[];
  tracks: Track[];
};

export const board = raw as Board;
