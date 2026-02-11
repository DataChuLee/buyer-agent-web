"use client";

import { useState } from "react";
import { useAuth } from "@/components/providers/auth-provider";

export default function GoogleAuthActions() {
  const { loading, user, isAuthenticated, signInWithGoogle, signOut } = useAuth();
  const [pending, setPending] = useState<"signin" | "signout" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSignIn = async () => {
    try {
      setError(null);
      setPending("signin");
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sign in.");
      setPending(null);
    }
  };

  const handleSignOut = async () => {
    try {
      setError(null);
      setPending("signout");
      await signOut();
      setPending(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sign out.");
      setPending(null);
    }
  };

  if (loading) {
    return (
      <button
        type="button"
        disabled
        className="mt-8 inline-flex w-full items-center justify-center gap-3 rounded-full border border-slate-300/80 bg-white px-6 py-3 text-sm font-medium text-slate-500 dark:border-white/20 dark:bg-white/10 dark:text-slate-300"
      >
        Checking session...
      </button>
    );
  }

  if (isAuthenticated && user) {
    return (
      <div className="mt-8 space-y-3">
        <p className="text-sm text-slate-700 dark:text-slate-200">
          Signed in as <span className="font-semibold">{user.email}</span>
        </p>
        <button
          type="button"
          onClick={handleSignOut}
          disabled={pending === "signout"}
          className="inline-flex w-full items-center justify-center gap-3 rounded-full border border-slate-300/80 bg-white px-6 py-3 text-sm font-medium text-slate-900 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/15"
        >
          {pending === "signout" ? "Signing out..." : "Sign out"}
        </button>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleSignIn}
        disabled={pending === "signin"}
        className="mt-8 inline-flex w-full items-center justify-center gap-3 rounded-full border border-slate-300/80 bg-white px-6 py-3 text-sm font-medium text-slate-900 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/15"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5">
          <path
            d="M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.5a4.7 4.7 0 0 1-2 3.1v2.6h3.2c1.9-1.8 3.1-4.4 3.1-7.5Z"
            fill="#4285F4"
          />
          <path
            d="M12 22c2.7 0 5-.9 6.7-2.4l-3.2-2.6c-.9.6-2.1 1-3.5 1-2.7 0-5-1.8-5.8-4.3H2.8v2.7A10 10 0 0 0 12 22Z"
            fill="#34A853"
          />
          <path
            d="M6.2 13.7a6.1 6.1 0 0 1 0-3.4V7.6H2.8a10 10 0 0 0 0 8.8l3.4-2.7Z"
            fill="#FBBC05"
          />
          <path
            d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.8-2.8A9.8 9.8 0 0 0 12 2a10 10 0 0 0-9.2 5.6l3.4 2.7C7 7.7 9.3 5.9 12 5.9Z"
            fill="#EA4335"
          />
        </svg>
        {pending === "signin" ? "Redirecting..." : "Continue with Google"}
      </button>

      {error ? <p className="mt-3 text-xs text-rose-600">{error}</p> : null}
    </div>
  );
}
