import Link from "next/link";
import Hero from "@/components/main/hero";
import ThemeToggle from "@/components/main/theme-toggle";
import BrandLogo from "@/components/brand-logo";
import { Indie_Flower } from "next/font/google";
import {
  Search,
  TrendingUp,
  Sparkles,
  Zap,
  Shield,
  Clock,
} from "lucide-react";

const indieFlower = Indie_Flower({
  weight: "400",
  subsets: ["latin"],
});

const features = [
  {
    icon: Search,
    title: "원하는 걸 말하면 끝",
    description:
      "\"요즘 핫한 노트북 추천해줘\"만 해도 OK. AI가 수천 개의 상품을 스캔해서 딱 맞는 걸 골라드려요.",
  },
  {
    icon: TrendingUp,
    title: "실시간 최저가 추적",
    description:
      "여러 판매처의 가격을 동시에 비교해요. 어디서 사야 가장 저렴한지 바로 알 수 있어요.",
  },
  {
    icon: Sparkles,
    title: "나만을 위한 추천",
    description:
      "쓸수록 취향을 더 잘 파악해요. 시간이 지날수록 추천이 더 정확해지는 AI 쇼핑 비서예요.",
  },
  {
    icon: Zap,
    title: "몇 초면 충분해요",
    description:
      "비교하고 분석하느라 몇 시간씩 낭비하지 마세요. Buyer Agent가 몇 초 만에 결과를 드려요.",
  },
  {
    icon: Shield,
    title: "검증된 판매자만",
    description:
      "신뢰할 수 없는 판매자는 걸러드려요. 믿을 수 있는 곳에서 안전하게 구매하세요.",
  },
  {
    icon: Clock,
    title: "언제든 24시간",
    description:
      "새벽 2시에 갑자기 필요한 게 생겼나요? Buyer Agent는 항상 깨어있어요.",
  },
];

const steps = [
  {
    number: "01",
    title: "원하는 걸 말해주세요",
    description:
      "\"가성비 좋은 무선 이어폰\"처럼 자유롭게 말해주세요. 구체적일수록 좋아요.",
  },
  {
    number: "02",
    title: "AI가 알아서 비교해요",
    description:
      "수백 개의 상품을 분석하고, 가격·품질·신뢰도를 종합해서 최선의 옵션을 추려요.",
  },
  {
    number: "03",
    title: "확신을 갖고 구매하세요",
    description:
      "왜 이 상품이 좋은지 근거와 함께 보여드려요. 더 이상 후회 없는 쇼핑을 하세요.",
  },
];

export default function Home() {
  return (
    <main className="bg-zinc-50 dark:bg-zinc-900">
      {/* ── Fixed Navbar ── */}
      <header className="fixed left-0 top-0 z-50 w-full border-b border-slate-200/60 bg-white/80 backdrop-blur-md dark:border-white/10 dark:bg-zinc-900/80">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 md:px-6 lg:px-8">
          <Link
            href="/"
            className="inline-flex items-center gap-2.5 transition hover:opacity-80"
          >
            <BrandLogo className="h-9" />
            <span className="text-sm font-bold tracking-tight text-slate-900 dark:text-white">
              BuyerAgent
            </span>
          </Link>

          <nav className="hidden items-center gap-8 text-sm font-medium text-slate-600 md:flex dark:text-slate-300">
            <a href="#features" className="transition hover:text-slate-900 dark:hover:text-white">
              기능
            </a>
            <a href="#how-it-works" className="transition hover:text-slate-900 dark:hover:text-white">
              사용법
            </a>
            <a href="#contact" className="transition hover:text-slate-900 dark:hover:text-white">
              문의
            </a>
          </nav>

          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link
              href="/dashboard"
              className="rounded-full bg-slate-900 px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
            >
              시작하기
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <Hero className="pt-16">
        <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col items-center px-6 text-center">
          {/* Headline */}
          <h1
            className={`${indieFlower.className} whitespace-nowrap text-4xl tracking-tight text-slate-900 sm:text-5xl md:text-6xl lg:text-7xl dark:text-white`}
          >
            Your Personal{" "}
            <span className="bg-gradient-to-r from-blue-600 to-violet-600 bg-clip-text text-transparent dark:from-blue-400 dark:to-violet-400">
              Buyer Agent
            </span>
          </h1>

          {/* Subtitle */}
          <p className="mt-6 max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg dark:text-slate-300">
            쇼핑할 때 수십 개의 탭을 열고, 가격 비교하고, 후기 읽느라 지치셨나요?{" "}
            <span className="font-semibold text-slate-900 dark:text-white">
              원하는 걸 말하기만 하면
            </span>{" "}
            Buyer Agent가 알아서 찾고, 비교하고, 최선의 선택을 알려드려요.
          </p>

          {/* CTAs */}
          <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row">
            <Link
              href="/dashboard"
              className="rounded-full bg-slate-900 px-8 py-3 text-sm font-semibold text-white shadow-lg transition hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
            >
              무료로 시작하기 →
            </Link>
            <a
              href="#how-it-works"
              className="rounded-full border border-slate-300 bg-white/70 px-8 py-3 text-sm font-semibold text-slate-700 backdrop-blur-sm transition hover:bg-white dark:border-white/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/15"
            >
              어떻게 작동하나요?
            </a>
          </div>
        </div>
      </Hero>

      {/* ── Features ── */}
      <section
        id="features"
        className="mx-auto max-w-7xl px-4 py-24 md:px-6 lg:px-8"
      >
        <div className="text-center">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl dark:text-white">
            쇼핑이 이렇게 쉬워도 되나요?
          </h2>
          <p className="mt-4 mx-auto max-w-xl text-slate-500 dark:text-slate-400">
            Buyer Agent는 AI와 실시간 데이터를 결합해서 당신만의 쇼핑 전문가가 되어드려요.
          </p>
        </div>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="group rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md dark:border-white/10 dark:bg-zinc-800/50"
            >
              <div className="mb-4 inline-flex size-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-500/10">
                <feature.icon className="size-5 text-blue-600 dark:text-blue-400" />
              </div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">
                {feature.title}
              </h3>
              <p className="text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── How It Works ── */}
      <section
        id="how-it-works"
        className="bg-slate-50 py-24 dark:bg-zinc-800/30"
      >
        <div className="mx-auto max-w-7xl px-4 md:px-6 lg:px-8">
          <div className="text-center">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl dark:text-white">
              3단계로 끝나는 스마트 쇼핑
            </h2>
            <p className="mt-4 text-slate-500 dark:text-slate-400">
              복잡한 설정 없이, 말 한마디면 시작돼요.
            </p>
          </div>

          <div className="mt-16 grid gap-10 md:grid-cols-3">
            {steps.map((step, i) => (
              <div key={step.number} className="relative text-center">
                {i < steps.length - 1 && (
                  <div className="absolute left-[calc(50%+2.5rem)] top-8 hidden h-px w-[calc(100%-5rem)] bg-slate-200 dark:bg-white/10 md:block" />
                )}
                <div className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-slate-900 text-lg font-bold text-white dark:bg-white dark:text-slate-900">
                  {step.number}
                </div>
                <h3 className="mb-2 text-base font-semibold text-slate-900 dark:text-white">
                  {step.title}
                </h3>
                <p className="text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA Banner ── */}
      <section id="contact" className="bg-slate-900 py-24 dark:bg-zinc-800">
        <div className="mx-auto max-w-3xl px-4 text-center md:px-6">
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            지금 바로 더 똑똑한 쇼핑을 시작하세요
          </h2>
          <p className="mt-4 text-slate-400">
            이미 수많은 사람들이 Buyer Agent와 함께 시간과 돈을 아끼고 있어요.
          </p>
          <Link
            href="/dashboard"
            className="mt-8 inline-block rounded-full bg-white px-8 py-3 text-sm font-semibold text-slate-900 shadow-lg transition hover:bg-slate-100"
          >
            무료로 시작하기 →
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-slate-200 bg-white py-8 dark:border-white/10 dark:bg-zinc-900">
        <div className="mx-auto max-w-7xl px-4 md:px-6 lg:px-8">
          <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
            <Link
              href="/"
              className="inline-flex items-center gap-2 transition hover:opacity-80"
            >
              <BrandLogo className="h-7" />
              <span className="text-xs font-bold text-slate-700 dark:text-slate-300">
                BuyerAgent
              </span>
            </Link>
            <p className="text-xs text-slate-400">
              © 2025 BuyerAgent. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </main>
  );
}
