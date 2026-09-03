import { describe, expect, it } from "vitest";

import { parseGcode } from "./gcode";

describe("parseGcode", () => {
  it("turns a feed move into a segment from the current position", () => {
    const { segments } = parseGcode("G1 X10 Y20");
    expect(segments).toEqual([
      { x1: 0, y1: 0, z1: 0, x2: 10, y2: 20, z2: 0, rapid: false },
    ]);
  });

  it("marks G0 as rapid and G1 as not", () => {
    const { segments } = parseGcode("G0 X5\nG1 X10");
    expect(segments.map((s) => s.rapid)).toEqual([true, false]);
  });

  it("carries the previous position into the next move", () => {
    const { segments } = parseGcode("G1 X10\nG1 Y5");
    expect(segments[1]).toMatchObject({ x1: 10, y1: 0, x2: 10, y2: 5 });
  });

  it("holds axes that a line does not mention", () => {
    const { segments } = parseGcode("G1 X10 Y20 Z5\nG1 X30");
    expect(segments[1]).toMatchObject({ y2: 20, z2: 5 });
  });

  // Motion is modal: a bare "X20" repeats whatever G0/G1 came before it.
  it("repeats the last motion mode for a line with only coordinates", () => {
    const { segments } = parseGcode("G1 X10\nX20");
    expect(segments).toHaveLength(2);
    expect(segments[1]).toMatchObject({ x1: 10, x2: 20, rapid: false });
  });

  it("emits nothing before a motion mode is set", () => {
    expect(parseGcode("X20 Y20").segments).toEqual([]);
  });

  it("ignores a move that goes nowhere", () => {
    expect(parseGcode("G1 X10\nG1 X10").segments).toHaveLength(1);
  });

  describe("coordinate modes", () => {
    it("treats G90 coordinates as absolute", () => {
      const { segments } = parseGcode("G90\nG1 X10\nG1 X15");
      expect(segments[1]).toMatchObject({ x1: 10, x2: 15 });
    });

    it("treats G91 coordinates as relative to the current position", () => {
      const { segments } = parseGcode("G91\nG1 X10\nG1 X15");
      expect(segments[1]).toMatchObject({ x1: 10, x2: 25 });
    });

    it("switches back to absolute when G90 follows G91", () => {
      const { segments } = parseGcode("G91\nG1 X10\nG90\nG1 X15");
      expect(segments[1]).toMatchObject({ x1: 10, x2: 15 });
    });
  });

  describe("units", () => {
    it("leaves millimetres alone under G21", () => {
      expect(parseGcode("G21\nG1 X10").segments[0].x2).toBe(10);
    });

    it("scales inches to millimetres under G20", () => {
      expect(parseGcode("G20\nG1 X1").segments[0].x2).toBeCloseTo(25.4);
    });

    // The scale applies as the line is read, so a mid-file switch is honoured
    // rather than retroactively rescaling what came before.
    it("applies a unit switch only to later moves", () => {
      const { segments } = parseGcode("G21\nG1 X10\nG20\nG1 X2");
      expect(segments[0].x2).toBe(10);
      expect(segments[1].x2).toBeCloseTo(50.8);
    });
  });

  describe("comments and junk", () => {
    it("strips a semicolon comment", () => {
      expect(parseGcode("G1 X10 ; move right").segments[0].x2).toBe(10);
    });

    it("strips a parenthesised comment from the middle of a line", () => {
      expect(parseGcode("G1 (fast) X10").segments[0].x2).toBe(10);
    });

    it("skips blank lines and whole-line comments", () => {
      expect(parseGcode("; header\n\n\nG1 X10").segments).toHaveLength(1);
    });

    it("ignores words it does not understand", () => {
      const { segments } = parseGcode("G1 X10 F800 S1000 M3");
      expect(segments).toHaveLength(1);
      expect(segments[0].x2).toBe(10);
    });

    it("ignores an unsupported motion code rather than guessing", () => {
      // G2/G3 arcs would need a centre and a direction; a straight line
      // between the endpoints would be a lie, so emit nothing.
      expect(parseGcode("G1 X10\nG2 X20 Y5 I5").segments).toHaveLength(1);
    });

    it("reads lowercase and unspaced words", () => {
      expect(parseGcode("g1x10y20").segments[0]).toMatchObject({
        x2: 10,
        y2: 20,
      });
    });

    it("accepts CRLF line endings", () => {
      expect(parseGcode("G1 X10\r\nG1 X20\r\n").segments).toHaveLength(2);
    });

    it("reads negative and decimal coordinates", () => {
      expect(parseGcode("G1 X-1.5 Y.25").segments[0]).toMatchObject({
        x2: -1.5,
        y2: 0.25,
      });
    });

    it("returns empty results for empty input", () => {
      const r = parseGcode("");
      expect(r.segments).toEqual([]);
      expect(r.drawLength).toBe(0);
      expect(r.bounds).toBeNull();
    });
  });

  describe("bounds", () => {
    it("covers every point the tool visits", () => {
      const { bounds } = parseGcode("G1 X10 Y5\nG1 X-2 Y8 Z3");
      expect(bounds).toEqual({
        minX: -2,
        maxX: 10,
        minY: 0,
        maxY: 8,
        minZ: 0,
        maxZ: 3,
      });
    });
  });

  describe("lengths", () => {
    it("counts feed moves as drawing and rapids as travel", () => {
      const { drawLength, travelLength } = parseGcode("G1 X3 Y4\nG0 X3 Y14");
      expect(drawLength).toBe(5);
      expect(travelLength).toBe(10);
    });

    it("measures in three dimensions", () => {
      expect(parseGcode("G1 Z3\nG1 X4").drawLength).toBe(7);
    });
  });

  describe("a real pcb_gcode.py file", () => {
    const gcode = [
      "; Generated by pcb_gcode.py",
      "; pen-up travel = 332.3 mm",
      "G21",
      "G90",
      "G0 Z5",
      "G0 X94.48 Y64.38 F3000",
      "G1 Z0 F3000",
      "G1 X95.5912 Y65.4912 F800",
      "G0 Z5",
    ].join("\n");

    it("separates the pen-down stroke from the pen-up moves", () => {
      const { segments } = parseGcode(gcode);
      const drawn = segments.filter((s) => !s.rapid);
      // Z5 -> Z0 plunge, then the one stroke across the board.
      expect(drawn).toHaveLength(2);
      expect(drawn[1]).toMatchObject({ x1: 94.48, y1: 64.38, z1: 0 });
    });

    it("keeps the pen-up moves at Z5", () => {
      const { segments } = parseGcode(gcode);
      const lift = segments.filter((s) => s.rapid).at(-1);
      expect(lift).toMatchObject({ z2: 5 });
    });
  });
});
