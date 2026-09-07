"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";

/*
  Session backed by the Python API + MongoDB.

  Accounts and boards live in Mongo. We keep a light session (name, email) in
  localStorage so the browser remembers who's signed in; every mutation goes
  through the API.

  There is deliberately no machine in here. The plotter is a USB cable
  plugged into the PC running the backend, not a possession of an account:
  it is connected on /connect and its live state comes from useMachine().
  Hanging it off the session would mean an account could "have" a machine
  that is not physically there.
*/

export type Session = {
  name: string;
  email: string;
};

type Result = { ok: boolean; error?: string };

type AuthCtx = {
  session: Session | null;
  ready: boolean;
  signUp: (name: string, email: string, password: string) => Promise<Result>;
  signIn: (email: string, password: string) => Promise<Result>;
  signOut: () => void;
};

const Ctx = createContext<AuthCtx | null>(null);
const KEY = "traceworks.session";

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
        persist({ name: user.name, email: user.email });
      }),

    signIn: (email, password) =>
      wrap(async () => {
        const user = await api.login(email, password);
        persist({ name: user.name, email: user.email });
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
