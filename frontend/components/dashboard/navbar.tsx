"use client";

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

const LogOutIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="m16 17 5-5-5-5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M21 12H9" strokeLinecap="round" strokeLinejoin="round" />
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
  const displayName =
    (typeof user?.user_metadata?.full_name === "string" && user.user_metadata.full_name) ||
    (typeof user?.user_metadata?.name === "string" && user.user_metadata.name) ||
    email.split("@")[0];
  const initials = displayName.slice(0, 1).toUpperCase();

  useEffect(() => {
    if (!open) return;
    const handleMouseDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <header className="relative z-20 flex h-16 w-full items-center justify-between bg-transparent">
      <div className="flex items-center gap-2">
        {!isDesktopViewport && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-slate-400 transition hover:bg-white/[0.08] hover:text-white"
            aria-label={isSidebarOpen ? "사이드바 닫기" : "사이드바 열기"}
          >
            {isSidebarOpen ? <SidebarCloseIcon className="h-4.5 w-4.5" /> : <SidebarOpenIcon className="h-4.5 w-4.5" />}
          </button>
        )}
      </div>

      {/* User menu */}
      <div ref={menuRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
          aria-haspopup="menu"
          className="flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-1.5 transition hover:bg-white/[0.08]"
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="프로필" className="h-7 w-7 rounded-full object-cover" />
          ) : (
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-violet-600 text-xs font-bold text-white">
              {initials}
            </span>
          )}
          <span className="hidden max-w-[100px] truncate text-[13px] font-medium text-slate-300 sm:block">
            {displayName}
          </span>
          <svg className="h-3.5 w-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {/* Dropdown */}
        <div
          className={cn(
            "absolute right-0 top-[calc(100%+8px)] w-60 rounded-2xl border border-white/[0.08] bg-[#111318]/95 p-3 shadow-2xl backdrop-blur-xl transition-all duration-150",
            open ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-1 opacity-0"
          )}
        >
          <div className="mb-2 flex items-center gap-2.5 px-1 pb-2 border-b border-white/[0.06]">
            {avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl} alt="프로필" className="h-8 w-8 rounded-full object-cover" />
            ) : (
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-violet-600 text-sm font-bold text-white">
                {initials}
              </span>
            )}
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold text-white">{displayName}</p>
              <p className="truncate text-[11px] text-slate-500">{email}</p>
            </div>
          </div>

          <button
            type="button"
            onClick={onSignOut}
            disabled={pendingSignOut}
            className="mt-1 flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[13px] text-slate-300 transition hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <LogOutIcon className="h-4 w-4 shrink-0 text-slate-500" />
            {pendingSignOut ? "로그아웃 중..." : "로그아웃"}
          </button>
        </div>
      </div>
    </header>
  );
}
