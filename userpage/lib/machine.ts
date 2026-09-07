"use client";

import { useEffect, useRef, useState } from "react";

import { API_URL, type ConsoleLine, type MachineSnapshot } from "@/lib/api";

const CONSOLE_LIMIT = 300;

function wsUrl(): string {
  // API_URL is an http(s) origin; the socket lives on the same one.
  return API_URL.replace(/^http/, "ws") + "/machine/ws";
}

/**
 * Subscribes to the machine's live state.
 *
 * Two different notions of "connected" live here and are deliberately not
 * merged: `live` is whether this browser is talking to the server, and
 * `snap.conn.connected` is whether the server is talking to the machine.
 * A page that conflates them tells you the plotter is offline when in fact
 * your own socket dropped, which sends you to check the wrong cable.
 */
export function useMachine() {
  const [snap, setSnap] = useState<MachineSnapshot | null>(null);
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const [live, setLive] = useState(false);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;

    function open() {
      ws = new WebSocket(wsUrl());

      ws.onopen = () => setLive(true);

      ws.onmessage = (ev) => {
        const frame = JSON.parse(ev.data);
        if (frame.type === "snapshot") {
          setSnap(frame.data as MachineSnapshot);
        } else if (frame.type === "console") {
          setLines((prev) =>
            [...prev, ...(frame.data as ConsoleLine[])].slice(-CONSOLE_LIMIT)
          );
        }
      };

      ws.onclose = () => {
        setLive(false);
        if (closed) return;
        // The server restarts constantly under --reload during development,
        // and a dropped socket that never comes back looks exactly like a
        // dead machine. Retry rather than making the user reload the page.
        retry.current = setTimeout(open, 1000);
      };

      ws.onerror = () => ws?.close();
    }

    open();
    return () => {
      closed = true;
      if (retry.current) clearTimeout(retry.current);
      ws?.close();
    };
  }, []);

  return {
    snap,
    console: lines,
    live,
    connected: Boolean(snap?.conn.connected),
  };
}
