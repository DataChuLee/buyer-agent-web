import Image from "next/image";
import Link from "next/link";
import Hero from "@/components/main/hero";
import ThemeToggle from "@/components/main/theme-toggle";
import { Indie_Flower } from "next/font/google";

const indieFlower = Indie_Flower({
  weight: "400",
  subsets: ["latin"],
});

export default function Home() {
  return (
    <Hero>
      <header className="absolute left-0 top-0 z-30 w-full">
        <div className="relative flex h-20 w-full items-center justify-between px-3 md:px-6 lg:px-8">
          <a href="#" className="flex items-center gap-3">
            <Image src="/buyeragent.png" alt="Buyer Agent logo" width={28} height={28} />
            <span className="text-sm font-medium text-slate-900 dark:text-white">Buyer Agent</span>
          </a>

          <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-8 text-sm font-medium text-slate-700 md:flex dark:text-slate-200">
            <a href="#features" className="transition hover:text-slate-900 dark:hover:text-white">
              Features
            </a>
            <a href="#pricing" className="transition hover:text-slate-900 dark:hover:text-white">
              Pricing
            </a>
            <a href="#contact" className="transition hover:text-slate-900 dark:hover:text-white">
              Contact
            </a>
          </nav>

          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link
              href="/auth"
              className="rounded-full border border-slate-300/80 bg-white/70 px-5 py-2 text-sm font-medium text-slate-900 backdrop-blur-sm transition hover:bg-white dark:border-white/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/15"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      <section className="relative z-10 mx-auto flex w-full max-w-4xl flex-col items-center px-6 text-center">
        <h1
          className={`${indieFlower.className} text-5xl tracking-tight text-slate-900 sm:text-6xl md:text-7xl dark:text-white`}
        >
          Your Personal AI Buyer Agent
        </h1>
        <p className="mt-8 max-w-2xl text-base leading-relaxed text-slate-700 sm:text-xl dark:text-slate-200">
          Tell us what you want, and Buyer Agent handles the rest. It discovers the best options,
          compares prices in real time, and helps you buy faster with confidence.
        </p>
        <div className="mt-8 flex items-center gap-3">
          <Link
            href="/auth"
            className="rounded-full border border-slate-300/80 bg-white/70 px-6 py-2.5 text-sm font-medium text-slate-900 backdrop-blur-sm transition hover:bg-white dark:border-white/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/15"
          >
            Get Started
          </Link>
        </div>
      </section>
    </Hero>
  );
}
