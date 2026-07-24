"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type Device } from "./api";

/*
  Session backed by the Python API + MongoDB.

  Accounts, paired devices, and boards all live in Mongo now. We keep a light
  session (name, email, and the paired device) in localStorage so the browser
  remembers who's signed in; every mutation goes through the API.
*/

export type Session = {
  name: string;
  email: string;
  device: Device | null;
};

type Result = { ok: boolean; error?: string };

type AuthCtx = {
  session: Session | null;
  ready: boolean;
  signUp: (name: string, email: string, password: string) => Promise<Result>;
  signIn: (email: string, password: string) => Promise<Result>;
  pairDevice: (deviceId: string) => Promise<Result>;
  renameDevice: (alias: string) => Promise<Result>;
  unpair: () => Promise<Result>;
  signOut: () => void;
};

const Ctx = createContext<AuthCtx | null>(null);
const KEY = "traceworks.session";

// Suggested demo ID (any non-empty ID pairs; this just pre-fills the field).
export const DEMO_DEVICE_ID = "TW-3F9A-C210";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setSession(JSON.parse(raw));
    } catch {}
    setReady(true);
  }, []);

  function persist(s: Session | null) {
    setSession(s);
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  }

  async function wrap(fn: () => Promise<void>): Promise<Result> {
    try {
      await fn();
      return { ok: true };
    } catch (e) {
      return { ok: false, error: (e as Error).message };
    }
  }

  const value: AuthCtx = {
    session,
    ready,
    signUp: (name, email, password) =>
      wrap(async () => {
        const user = await api.signup(name, email, password);
        persist({ name: user.name, email: user.email, device: null });
      }),

    signIn: (email, password) =>
      wrap(async () => {
        const user = await api.login(email, password);
        const device = await api.getDevice(user.email);
        persist({ name: user.name, email: user.email, device });
      }),

    pairDevice: (deviceId) =>
      wrap(async () => {
        // pairing straight from the landing page, before an account exists,
        // creates a lightweight guest account first.
        let s = session;
        if (!s) {
          const guest = await api.signup(
            "Guest",
            `guest+${Date.now()}@traceworks.dev`,
            crypto.randomUUID()
          );
          s = { name: guest.name, email: guest.email, device: null };
        }
        const device = await api.pairDevice(s.email, deviceId);
        persist({ ...s, device });
      }),

    renameDevice: (alias) =>
      wrap(async () => {
        if (!session?.device) return;
        const device = await api.renameDevice(session.email, alias);
        persist({ ...session, device });
      }),

    unpair: () =>
      wrap(async () => {
        if (!session) return;
        await api.unpair(session.email);
        persist({ ...session, device: null });
      }),

    signOut: () => persist(null),
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
