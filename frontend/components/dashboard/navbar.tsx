"use client";

import Link from "next/link";
import { useState } from "react";
import type { User } from "@supabase/supabase-js";
import { cn } from "@/lib/utils";

interface DashboardNavbarProps {
  user: User | null;
  pendingSignOut: boolean;
  onSignOut: () => Promise<void> | void;
}

const floatingButtonClass =
  "inline-flex items-center gap-2 rounded-2xl bg-white/10 px-4 py-2 text-sm text-white shadow-[0_18px_35px_-22px_rgba(0,0,0,0.95)] backdrop-blur-xl transition hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70";

export default function DashboardNavbar({
  user,
  pendingSignOut,
  onSignOut,
}: DashboardNavbarProps) {
  const [open, setOpen] = useState(false);

  const avatarUrl =
    (typeof user?.user_metadata?.avatar_url === "string" && user.user_metadata.avatar_url) ||
    (typeof user?.user_metadata?.picture === "string" && user.user_metadata.picture) ||
    null;
  const email = user?.email ?? "Unknown user";
  const initials = email.slice(0, 1).toUpperCase();

  return (
    <header className="relative z-20 flex w-full items-center justify-between bg-transparent">
      <Link href="/" className={floatingButtonClass}>
        <span className="text-base font-extrabold tracking-wide">Buyer Agent</span>
      </Link>

      <div
        className="relative"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocusCapture={() => setOpen(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setOpen(false);
          }
        }}
      >
        <button type="button" className={cn(floatingButtonClass, "min-w-[56px] justify-center px-3")}>
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="Profile" className="h-8 w-8 rounded-full object-cover" />
          ) : (
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-sm font-semibold">
              {initials}
            </span>
          )}
        </button>

        <div
          className={cn(
            "absolute right-0 top-[calc(100%+10px)] w-56 rounded-2xl bg-black/70 p-3 shadow-[0_24px_48px_-26px_rgba(0,0,0,1)] backdrop-blur-xl transition",
            open ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-1 opacity-0"
          )}
        >
          <p className="truncate text-xs text-slate-300">{email}</p>
          <button
            type="button"
            onClick={onSignOut}
            disabled={pendingSignOut}
            className="mt-2 w-full rounded-xl bg-white/10 px-3 py-2 text-left text-sm text-white transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pendingSignOut ? "Signing out..." : "Sign out"}
          </button>
        </div>
      </div>
    </header>
  );
}
