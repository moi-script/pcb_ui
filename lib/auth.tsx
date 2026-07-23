"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/*
  Prototype session model.

  The product's core idea: a plotter ships with a unique DEVICE ID printed on
  it (and shown in the FluidNC console). An account is bound to one or more
  device IDs — that pairing is what links "your account" to "your machine".
  Here that flow is simulated with localStorage so the whole journey —
  create account → sign in → pair device → control it — is walkable without a
  backend. Swap these functions for real API calls later.
*/

export type Session = {
  email: string;
  name: string;
  deviceId: string | null;
};

type AuthCtx = {
  session: Session | null;
  ready: boolean;
  signUp: (name: string, email: string) => void;
  signIn: (email: string) => void;
  pairDevice: (deviceId: string) => void;
  unpair: () => void;
  signOut: () => void;
};

const Ctx = createContext<AuthCtx | null>(null);
const KEY = "traceworks.session";

// The one ID this demo machine will accept, matching lib/data.ts.
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

  const value: AuthCtx = {
    session,
    ready,
    signUp: (name, email) => persist({ name, email, deviceId: null }),
    signIn: (email) =>
      persist({
        name: session?.name ?? email.split("@")[0],
        email,
        deviceId: session?.deviceId ?? null,
      }),
    pairDevice: (deviceId) =>
      persist(
        session
          ? { ...session, deviceId }
          : // pairing straight from the landing CTA, before an account exists
            { name: "Guest", email: "guest@traceworks.dev", deviceId }
      ),
    unpair: () => persist(session ? { ...session, deviceId: null } : null),
    signOut: () => persist(null),
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
