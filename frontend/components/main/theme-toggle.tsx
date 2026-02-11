"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ThemeToggleProps {
  className?: string;
}

type ThemeMode = "dark" | "light";

export default function ThemeToggle({ className }: ThemeToggleProps) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") return "dark";
    const saved = window.localStorage.getItem("theme-mode");
    return saved === "light" ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", mode === "dark");
    window.localStorage.setItem("theme-mode", mode);
  }, [mode]);

  return (
    <div
      className={cn(
        "relative inline-flex h-10 w-[96px] items-center rounded-full border p-1 backdrop-blur-sm transition",
        "border-slate-300/80 bg-white/75 dark:border-white/20 dark:bg-black/35",
        className
      )}
      role="group"
      aria-label="Theme toggle"
    >
      <span
        className={cn(
          "pointer-events-none absolute top-1 h-8 w-11 rounded-full shadow-sm transition-transform duration-300",
          mode === "light"
            ? "translate-x-0 bg-white"
            : "translate-x-10 bg-zinc-900 dark:bg-white"
        )}
      />

      <button
        type="button"
        onClick={() => setMode("light")}
        aria-label="Switch to light mode"
        className={cn(
          "relative z-10 flex h-8 w-11 items-center justify-center rounded-full text-base transition",
          mode === "light"
            ? "text-slate-900"
            : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
        )}
      >
        <span className="leading-none">🌤️</span>
      </button>
      <button
        type="button"
        onClick={() => setMode("dark")}
        aria-label="Switch to dark mode"
        className={cn(
          "relative z-10 flex h-8 w-11 items-center justify-center rounded-full text-base transition",
          mode === "dark"
            ? "text-white dark:text-slate-900"
            : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
        )}
      >
        <span className="leading-none">🌙</span>
      </button>
    </div>
  );
}
