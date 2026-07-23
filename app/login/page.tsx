"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Logo from "@/components/Logo";
import AuthAside from "@/components/AuthAside";
import { useAuth } from "@/lib/auth";

export default function LogIn() {
  const { signIn, session } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !pw) return;
    signIn(email);
    // If already paired, go straight to the dashboard; otherwise pair first.
    router.push(session?.deviceId ? "/dashboard" : "/connect");
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <main className="substrate flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center">
          <div className="mx-auto w-full max-w-sm py-12">
            <span className="tlabel">Welcome back</span>
            <h1 className="mt-3 text-3xl tracking-tight text-ink">
              Sign in to your bench.
            </h1>

            <form onSubmit={submit} className="mt-8 space-y-4">
              <label className="block">
                <span className="tlabel">Email</span>
                <input
                  className="field mt-1.5"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ada@workshop.dev"
                  autoComplete="email"
                />
              </label>
              <label className="block">
                <div className="flex items-center justify-between">
                  <span className="tlabel">Password</span>
                  <span className="text-xs text-faint hover:text-copper cursor-pointer">
                    forgot?
                  </span>
                </div>
                <input
                  className="field mt-1.5"
                  type="password"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
              </label>
              <button className="btn btn-primary w-full" type="submit">
                Sign in →
              </button>
            </form>

            <div className="mt-6 rounded border border-line bg-panel p-3 text-xs text-muted">
              <span className="tlabel">demo</span>
              <p className="mt-1 font-mono">
                Any email + password works. You&apos;ll pair the demo machine{" "}
                <span className="text-copper">TW-3F9A-C210</span> next.
              </p>
            </div>

            <p className="mt-6 text-sm text-muted">
              New here?{" "}
              <Link href="/signup" className="text-copper hover:underline">
                Create an account
              </Link>
            </p>
          </div>
        </div>
      </main>

      <AuthAside caption="// You only see the machines paired to your account. Sign in and the bench is right where you left it." />
    </div>
  );
}
