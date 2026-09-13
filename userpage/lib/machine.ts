"use client";

import { useSyncExternalStore } from "react";

import { API_URL, type ConsoleLine, type MachineSnapshot } from "@/lib/api";

const CONSOLE_LIMIT = 300;

// How long the socket outlives its last subscriber. Moving between pages
// unmounts one page's hooks a moment before the next page's mount, and a
// socket closed in that gap forgets the machine: the next page would say
// "No machine connected" mid-plot until a fresh snapshot arrived.
const IDLE_CLOSE_MS = 5000;

function wsUrl(): string {
  // API_URL is an http(s) origin; the socket lives on the same one. Empty
  // means this page's own origin (the desktop build).
  const origin = API_URL || window.location.origin;
  return origin.replace(/^http/, "ws") + "/machine/ws";
}

type Store = {
  snap: MachineSnapshot | null;
  lines: ConsoleLine[];
  live: boolean;
};

// One socket and one copy of the machine's state for the whole app. Every
// page, header and panel that asks for the machine reads the same values,
// so they cannot disagree, and a page opened mid-plot starts from what is
// already known instead of from nothing.
let store: Store = { snap: null, lines: [], live: false };
const listeners = new Set<() => void>();
let socket: WebSocket | null = null;
let retry: ReturnType<typeof setTimeout> | null = null;
let idleClose: ReturnType<typeof setTimeout> | null = null;

function update(patch: Partial<Store>) {
  store = { ...store, ...patch };
  listeners.forEach((l) => l());
}

function open() {
  if (socket) return;
  const ws = new WebSocket(wsUrl());
  socket = ws;

  ws.onopen = () => update({ live: true });

  ws.onmessage = (ev) => {
    const frame = JSON.parse(ev.data);
    if (frame.type === "snapshot") {
      update({ snap: frame.data as MachineSnapshot });
    } else if (frame.type === "console") {
      update({
        lines: [...store.lines, ...(frame.data as ConsoleLine[])].slice(
          -CONSOLE_LIMIT
        ),
      });
    }
  };

  ws.onclose = () => {
    if (socket === ws) socket = null;
    update({ live: false });
    if (listeners.size === 0) return;
    // The server restarts constantly under --reload during development,
    // and a dropped socket that never comes back looks exactly like a
    // dead machine. Retry rather than making the user reload the page.
    retry = setTimeout(open, 1000);
  };

  ws.onerror = () => ws.close();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (idleClose) {
    clearTimeout(idleClose);
    idleClose = null;
  }
  open();
  return () => {
    listeners.delete(listener);
    if (listeners.size > 0) return;
    idleClose = setTimeout(() => {
      idleClose = null;
      if (listeners.size > 0) return;
      if (retry) clearTimeout(retry);
      retry = null;
      socket?.close();
    }, IDLE_CLOSE_MS);
  };
}

const getSnapshot = () => store;
const getServerSnapshot = () => store;

/**
 * Subscribes to the machine's live state.
 *
 * Two different notions of "connected" live here and are deliberately not
 * merged: `live` is whether this browser is talking to the server, and
 * `snap.conn.connected` is whether the server is talking to the machine.
 * A page that conflates them tells you the plotter is offline when in fact
 * your own socket dropped, which sends you to check the wrong cable.
 *
 * A third: `ready` is false until the server has described the machine at
 * all. Until then "not connected" is unknown, not a fact, and a page that
 * shows a Connect button on it invites a reconnect that would reset the
 * board in the middle of a plot.
 */
export function useMachine() {
  const s = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return {
    snap: s.snap,
    console: s.lines,
    live: s.live,
    ready: s.snap !== null,
    connected: Boolean(s.snap?.conn.connected),
  };
}
