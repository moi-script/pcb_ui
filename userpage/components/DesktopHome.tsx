"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The desktop app has no landing page or sign-up: home is the workbench.
export default function DesktopHome() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center bg-paper">
      <span className="tlabel animate-pulse">loading workbench…</span>
    </div>
  );
}
