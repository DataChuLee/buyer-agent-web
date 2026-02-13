import { Indie_Flower } from "next/font/google";
import Hero from "@/components/main/hero";
import ThemeToggle from "@/components/main/theme-toggle";
import BackButton from "@/components/main/back-button";
import GoogleAuthActions from "@/components/auth/google-auth-actions";

const indieFlower = Indie_Flower({
  weight: "400",
  subsets: ["latin"],
});

export default function AuthPage() {
  return (
    <Hero>
      <header className="absolute left-0 top-0 z-30 w-full">
        <div className="relative flex h-20 w-full items-center justify-between px-3 md:px-6 lg:px-8">
          <BackButton />
          <ThemeToggle />
        </div>
      </header>

      <section className="relative z-10 w-full px-6">
        <div className="mx-auto w-full max-w-md rounded-3xl border border-slate-200/70 bg-white/70 p-8 text-center shadow-2xl backdrop-blur-sm dark:border-white/10 dark:bg-zinc-900/60">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-300">
            Dashboard Access
          </p>
          <h1
            className={`${indieFlower.className} mt-4 text-4xl leading-tight text-slate-900 sm:text-5xl dark:text-white`}
          >
            Sign in to continue
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            Use Google once and move directly into your Buyer Agent dashboard.
          </p>

          <GoogleAuthActions />

          <p className="mt-5 text-xs text-slate-500 dark:text-slate-400">
            By continuing, you agree to our Terms and Privacy Policy.
          </p>
        </div>
      </section>
    </Hero>
  );
}
