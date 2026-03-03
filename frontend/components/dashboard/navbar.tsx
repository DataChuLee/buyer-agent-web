"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { cn } from "@/lib/utils";

interface DashboardNavbarProps {
  user: User | null;
  pendingSignOut: boolean;
  onSignOut: () => Promise<void> | void;
  onToggleSidebar?: () => void;
  isSidebarOpen?: boolean;
  isDesktopViewport?: boolean;
}

const brandLinkClass =
  "inline-flex items-center text-base font-extrabold tracking-wide text-white transition hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70";

const avatarButtonClass =
  "inline-flex items-center justify-center rounded-full text-white transition hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70";

const SidebarOpenIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <rect x="3.5" y="5" width="17" height="14" rx="2" />
    <path d="M9 5v14" strokeLinecap="round" />
    <path d="m14.5 10 3 2-3 2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SidebarCloseIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <rect x="3.5" y="5" width="17" height="14" rx="2" />
    <path d="M9 5v14" strokeLinecap="round" />
    <path d="m16.5 10-3 2 3 2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function DashboardNavbar({
  user,
  pendingSignOut,
  onSignOut,
  onToggleSidebar,
  isSidebarOpen = false,
  isDesktopViewport = false,
}: DashboardNavbarProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const avatarUrl =
    (typeof user?.user_metadata?.avatar_url === "string" && user.user_metadata.avatar_url) ||
    (typeof user?.user_metadata?.picture === "string" && user.user_metadata.picture) ||
    null;
  const email = user?.email ?? "Unknown user";
  const initials = email.slice(0, 1).toUpperCase();

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleMouseDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <header className="relative z-20 flex h-20 w-full items-center justify-between bg-transparent">
      <div className="flex items-center gap-3">
        {isDesktopViewport ? (
          <Link href="/" className={brandLinkClass}>
            Buyer Agent
          </Link>
        ) : (
          <>
            <button
              type="button"
              onClick={onToggleSidebar}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/[0.05] text-white transition hover:bg-white/[0.1]"
              aria-label={isSidebarOpen ? "Close history sidebar" : "Open history sidebar"}
            >
              {isSidebarOpen ? <SidebarCloseIcon className="h-5 w-5" /> : <SidebarOpenIcon className="h-5 w-5" />}
            </button>
            <Link href="/" className={brandLinkClass}>
              Buyer Agent
            </Link>
          </>
        )}
      </div>

      <div ref={menuRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
          aria-haspopup="menu"
          className={cn(avatarButtonClass, "h-9 w-9")}
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="Profile" className="h-9 w-9 rounded-full object-cover" />
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
