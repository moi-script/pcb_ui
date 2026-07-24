// Client for the TraceWorks Python API (FastAPI, default http://localhost:8000).
// Set NEXT_PUBLIC_API_URL to point elsewhere.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type User = { name: string; email: string };

export type Device = {
  id: string;
  alias: string;
  firmware: string;
  controller: string;
  connection: string;
  port: string;
  bed: string;
  penUpZ: number;
  penDownZ: number;
  travelFeed: number;
  drawFeed: number;
};

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
};

export type PrintStart = { ok: boolean; total: number; check: boolean };

export type PrintState =
  | "idle"
  | "checking"
  | "printing"
  | "done"
  | "error"
  | "stopped";

export type PrintStatus = {
  state: PrintState;
  line: number;
  total: number;
  error?: string;
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

  getDevice: (email: string) =>
    req<Device | null>(`/devices/${encodeURIComponent(email)}`),

  pairDevice: (email: string, deviceId: string) =>
    req<Device>("/devices/pair", {
      method: "POST",
      body: JSON.stringify({ email, device_id: deviceId }),
    }),

  unpair: (email: string) =>
    req<{ ok: boolean }>("/devices/unpair", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  listBoards: (email: string) =>
    req<Board[]>(`/boards/${encodeURIComponent(email)}`),

  getBoard: (id: string) => req<Board>(`/board/${id}`),

  renameBoard: (id: string, name: string) =>
    req<Board>(`/board/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  renameDevice: (email: string, alias: string) =>
    req<Device>(`/devices/${encodeURIComponent(email)}`, {
      method: "PATCH",
      body: JSON.stringify({ alias }),
    }),

  deleteBoard: (id: string) =>
    req<{ ok: boolean }>(`/board/${id}`, { method: "DELETE" }),

  // --- print streaming (backend relays to the ESP32 bridge) ---
  startPrint: (email: string, boardId: string, check: boolean) =>
    req<PrintStart>("/print", {
      method: "POST",
      body: JSON.stringify({ email, board_id: boardId, check }),
    }),

  printStatus: (email: string) =>
    req<PrintStatus>(`/print/status/${encodeURIComponent(email)}`),

  stopPrint: (email: string) =>
    req<{ ok: boolean }>("/print/stop", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

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
};
