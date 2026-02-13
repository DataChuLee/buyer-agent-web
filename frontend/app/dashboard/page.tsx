"use client";

import { useEffect, useState } from "react";
import { Indie_Flower } from "next/font/google";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/auth-provider";
import DashboardNavbar from "@/components/dashboard/navbar";
import PromptArea from "@/components/dashboard/prompt-area";

const indieFlower = Indie_Flower({
  subsets: ["latin"],
  weight: "400",
});

export default function DashboardPage() {
  const router = useRouter();
  const { loading, isAuthenticated, user, signOut } = useAuth();
  const [pendingSignOut, setPendingSignOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, loading, router]);

  const handleSignOut = async () => {
    try {
      setError(null);
      setPendingSignOut(true);
      await signOut();
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sign out.");
      setPendingSignOut(false);
    }
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#181818] text-slate-200">
        Loading dashboard...
      </main>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  const handlePromptSubmit = () => {
    setError(null);
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-black text-slate-100">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(rgba(148,163,184,0.16) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.16) 1px, transparent 1px)",
          backgroundSize: "42px 42px",
        }}
      />

      <div className="relative z-10 flex min-h-screen w-full flex-col px-6 pb-8 pt-6 md:px-8 md:pt-8">
        <DashboardNavbar user={user} pendingSignOut={pendingSignOut} onSignOut={handleSignOut} />

        <section className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-4xl">
            <h1 className={`${indieFlower.className} mb-7 text-center text-4xl tracking-tight text-white md:text-5xl`}>
              What can I help you buy today?
            </h1>
            <PromptArea onSubmit={handlePromptSubmit} />
            {error ? <p className="mt-4 text-center text-sm text-rose-400">{error}</p> : null}
          </div>
        </section>
      </div>
    </main>
  );
}
