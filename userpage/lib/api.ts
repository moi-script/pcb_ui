// Client for the TraceWorks Python API (FastAPI, default http://localhost:8000).
// Set NEXT_PUBLIC_API_URL to point elsewhere.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type User = { name: string; email: string };

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
  id: string;
  name: string;
  filename: string;
  width: number;
  height: number;
  fcu: number;
  bcu: number;
  nets: number;
  layer: "F.Cu" | "B.Cu";
  gcodeLines: number;
  drawMoves: number;
  travelMoves: number;
  penUpBefore: number;
  penUpAfter: number;
  size: string;
  estMinutes: number;
  status: string;
  createdAt: string;
  tracks?: Track[];
  gcode?: string;
  /** traced boards only — the authoritative geometry the G-code came from */
  strokes?: number[][][];
  source?: "kicad" | "image";
  traceParams?: TraceParams;
  traceInfo?: TraceInfo;
  frameGcode?: string;
  /** false for KiCad boards, and for images traced before sources were kept */
  hasSource?: boolean;
};

export type TraceMode = "centerline" | "outline" | "fill";

export type TraceParams = {
  /** longest edge in mm; 0 fits the bed */
  size_mm: number;
  mode: TraceMode;
  preset: "line" | "pcb";
  /** null means Otsu picks it */
  threshold: number | null;
  invert: boolean;
  /** fill mode only — gap between hatch lines; must be <= the pen width */
  hatch_spacing_mm?: number;
  hatch_angle?: number;
  hatch_cross?: boolean;
};

export type TraceInfo = {
  inkCoverage: number;
  strokeCount: number;
  warnings: string[];
};

export type PortInfo = {
  device: string;
  description: string;
  chip: string | null;
  likely_controller: boolean;
};

export type PortList = {
  ports: PortInfo[];
  /** Filled only when exactly one candidate was found — never a guess. */
  suggested: string | null;
  bauds: number[];
};

export type JobState =
  | "idle" | "running" | "paused" | "done" | "error" | "stopped";

export type JobSnapshot = {
  name: string;
  state: JobState;
  /** Lines handed to the controller. Runs ahead of the pen. */
  sent: number;
  /** Lines the controller has parsed and queued. Also ahead of the pen. */
  acked: number;
  total: number;
  check: boolean;
  error: string | null;
  errorLine: number | null;
};

export type MachineSnapshot = {
  conn: {
    connected: boolean;
    port: string | null;
    baud: number;
    firmware: string;
    profile: string;
    penMode: string;
    travel: [number, number, number];
  };
  state: string;
  mpos: [number, number, number];
  wpos: [number, number, number];
  wco: [number, number, number];
  feed: number;
  spindle: number;
  pen: string;
  alarm: string | null;
  error: string | null;
  job: JobSnapshot | null;
  seq: number;
};

export type ConsoleLine = {
  direction: string;
  text: string;
  kind: string;
  seq: number;
};

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch {
    throw new Error(
      "Can't reach the server. Is the API running on " + API_URL + "?"
    );
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new Error(data?.detail || `Request failed (${res.status}).`);
  }
  return data as T;
}

export const api = {
  signup: (name: string, email: string, password: string) =>
    req<User>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    }),

  login: (email: string, password: string) =>
    req<User>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  listBoards: (email: string) =>
    req<Board[]>(`/boards/${encodeURIComponent(email)}`),

  getBoard: (id: string) => req<Board>(`/board/${id}`),

  renameBoard: (id: string, name: string) =>
    req<Board>(`/board/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  deleteBoard: (id: string) =>
    req<{ ok: boolean }>(`/board/${id}`, { method: "DELETE" }),

  // --- machine (USB serial, owned by the backend on this same PC) ---
  machinePorts: () => req<PortList>("/machine/ports"),

  machineConnect: (port: string, baud: number, email?: string) =>
    req<{ ok: boolean; firmware: string }>("/machine/connect", {
      method: "POST",
      body: JSON.stringify({ port, baud, email }),
    }),

  machineDisconnect: () =>
    req<{ ok: boolean }>("/machine/disconnect", { method: "POST" }),

  machineState: () => req<MachineSnapshot>("/machine/state"),

  machineLast: (email: string) =>
    req<{ port: string; baud: number } | null>(
      `/machine/last?email=${encodeURIComponent(email)}`
    ),

  jog: (axis: string, distance: number, feed = 1000) =>
    req<{ ok: boolean }>("/machine/jog", {
      method: "POST",
      body: JSON.stringify({ axis, distance, feed }),
    }),

  jogCancel: () =>
    req<{ ok: boolean }>("/machine/jog/cancel", { method: "POST" }),

  home: () => req<{ ok: boolean }>("/machine/home", { method: "POST" }),

  unlock: () => req<{ ok: boolean }>("/machine/unlock", { method: "POST" }),

  zero: (axes: string) =>
    req<{ ok: boolean }>("/machine/zero", {
      method: "POST",
      body: JSON.stringify({ axes }),
    }),

  command: (line: string) =>
    req<{ ok: boolean }>("/machine/command", {
      method: "POST",
      body: JSON.stringify({ line }),
    }),

  estop: () => req<{ ok: boolean }>("/machine/estop", { method: "POST" }),

  run: (boardId: string, check: boolean) =>
    req<{ ok: boolean; total: number; check: boolean }>("/machine/run", {
      method: "POST",
      body: JSON.stringify({ board_id: boardId, check }),
    }),

  pauseJob: () => req<{ ok: boolean }>("/machine/pause", { method: "POST" }),
  resumeJob: () => req<{ ok: boolean }>("/machine/resume", { method: "POST" }),
  stopJob: () => req<{ ok: boolean }>("/machine/stop", { method: "POST" }),

  // multipart upload -> route -> stored board
  async route(file: File, email: string): Promise<Board> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("email", email);
    let res: Response;
    try {
      res = await fetch(`${API_URL}/route`, { method: "POST", body: fd });
    } catch {
      throw new Error("Can't reach the server. Is the API running?");
    }
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error(data?.detail || "Routing failed.");
    return data as Board;
  },

  // multipart upload -> centerline trace -> stored board
  async trace(file: File, email: string, params: TraceParams): Promise<Board> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("email", email);
    fd.append("size_mm", String(params.size_mm));
    fd.append("mode", params.mode);
    fd.append("preset", params.preset);
    fd.append("invert", String(params.invert));
    if (params.mode === "fill") {
      fd.append("hatch_spacing_mm", String(params.hatch_spacing_mm ?? 0.4));
      fd.append("hatch_angle", String(params.hatch_angle ?? 45));
      fd.append("hatch_cross", String(params.hatch_cross ?? false));
    }
    // omitted entirely means "pick it automatically" on the server
    if (params.threshold !== null) {
      fd.append("threshold", String(params.threshold));
    }
    let res: Response;
    try {
      res = await fetch(`${API_URL}/trace`, { method: "POST", body: fd });
    } catch {
      throw new Error("Can't reach the server. Is the API running?");
    }
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error(data?.detail || "Tracing failed.");
    return data as Board;
  },

  // re-run the stored source image with different settings, in place
  retrace: (boardId: string, params: TraceParams) =>
    req<Board>(`/board/${boardId}/retrace`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
};
