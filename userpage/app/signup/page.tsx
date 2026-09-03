"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Logo from "@/components/Logo";
import AuthAside from "@/components/AuthAside";
import { useAuth } from "@/lib/auth";

export default function SignUp() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !email || !pw) return;
    setBusy(true);
    setError(null);
    const res = await signUp(name, email, pw);
    if (res.ok) router.push("/connect");
    else {
      setError(res.error ?? "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <main className="substrate flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center">
          <div className="mx-auto w-full max-w-sm py-12">
            <span className="tlabel">Step 1 of 2 · create account</span>
            <h1 className="mt-3 text-3xl tracking-tight text-ink">
              Set up your workbench.
            </h1>
            <p className="mt-3 text-sm text-muted">
              Create an account, then pair your plotter by its device ID.
            </p>

            <form onSubmit={submit} className="mt-8 space-y-4">
              <Labeled label="Name">
                <input
                  className="field"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ada Lovelace"
                  autoComplete="name"
                />
              </Labeled>
              <Labeled label="Email">
                <input
                  className="field"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ada@workshop.dev"
                  autoComplete="email"
                />
              </Labeled>
              <Labeled label="Password">
                <input
                  className="field"
                  type="password"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                />
              </Labeled>
              {error && (
                <p className="text-sm text-danger">{error}</p>
              )}
              <button
                className="btn btn-copper w-full"
                type="submit"
                disabled={busy}
              >
                {busy ? "Creating…" : "Create account →"}
              </button>
            </form>

            <p className="mt-6 text-sm text-muted">
              Already have one?{" "}
              <Link href="/login" className="text-copper hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </main>

      <AuthAside caption="// Next you'll pair a machine by typing in the device ID printed on its controller." />
    </div>
  );
}

function Labeled({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="tlabel">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}
