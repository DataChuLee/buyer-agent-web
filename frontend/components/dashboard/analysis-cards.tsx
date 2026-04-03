"use client";

import Image from "next/image";

type AnalysisItem = {
  name: string;
  seller?: string | null;
  price?: string | null;
  size?: string | null;
  features: string[];
  image?: string | null;
  url?: string | null;
};

type AnalysisCardsProps = {
  analysis: AnalysisItem[];
};

const ShoeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 44 C8 44 14 28 28 24 C36 22 46 26 52 22 C56 20 58 16 58 16" />
    <path d="M8 44 C8 44 10 50 16 52 C22 54 30 52 36 50 C44 48 52 48 56 44 C60 40 58 34 52 32 C46 30 38 34 30 36 C20 38 12 36 8 44Z" fill="currentColor" fillOpacity="0.12" />
    <circle cx="22" cy="40" r="2.5" fill="currentColor" />
    <circle cx="34" cy="37" r="2.5" fill="currentColor" />
    <circle cx="44" cy="40" r="2.5" fill="currentColor" />
  </svg>
);

const ExternalLinkIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="15 3 21 3 21 9" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="10" y1="14" x2="21" y2="3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const rankStyles = [
  { badge: "bg-amber-400/15 text-amber-300 ring-1 ring-amber-400/30", label: "1위" },
  { badge: "bg-slate-400/15 text-slate-300 ring-1 ring-slate-400/30", label: "2위" },
  { badge: "bg-orange-700/15 text-orange-400 ring-1 ring-orange-700/30", label: "3위" },
];

export default function AnalysisCards({ analysis }: AnalysisCardsProps) {
  if (!analysis || analysis.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 w-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-1">
        <span className="h-1 w-4 rounded-full bg-blue-500" />
        <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
          제품 비교 분석
        </p>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {analysis.map((item, idx) => {
          const rank = rankStyles[idx] ?? null;
          return (
            <div
              key={idx}
              className="group relative flex flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-[#13141a] transition duration-200 hover:border-white/[0.14] hover:bg-[#16171e]"
            >

              {/* Image area */}
              <div className="relative flex h-44 items-center justify-center overflow-hidden bg-gradient-to-b from-white/[0.04] to-transparent">
                {item.image ? (
                  <Image
                    src={item.image}
                    alt={item.name}
                    fill
                    className="object-contain p-4 drop-shadow-2xl transition duration-300 group-hover:scale-[1.03]"
                    unoptimized
                  />
                ) : (
                  <ShoeIcon className="h-20 w-20 text-slate-700" />
                )}
              </div>

              {/* Divider */}
              <div className="h-px bg-white/[0.05]" />

              {/* Info */}
              <div className="flex flex-1 flex-col gap-2.5 p-4">
                {/* Seller */}
                {item.seller && (
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-600">
                    {item.seller}
                  </p>
                )}

                {/* Name */}
                <h3 className="text-[14px] font-bold leading-snug text-white">
                  {item.name}
                </h3>

                {/* Price + Size row */}
                <div className="flex flex-wrap items-center gap-1.5">
                  {item.price && (
                    <span className="rounded-lg bg-blue-500/15 px-2.5 py-1 text-[13px] font-bold text-blue-300 ring-1 ring-blue-500/20">
                      {item.price}
                    </span>
                  )}
                  {item.size && (
                    <span className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-500">
                      {item.size}
                    </span>
                  )}
                </div>

                {/* Features */}
                {item.features.length > 0 && (
                  <ul className="flex flex-1 flex-col gap-1.5">
                    {item.features.map((feature, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-400">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-600" />
                        {feature}
                      </li>
                    ))}
                  </ul>
                )}

                {/* CTA */}
                <div className="mt-auto pt-1">
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex flex-col items-center justify-center gap-0.5 rounded-xl bg-white px-4 py-2.5 text-black transition hover:bg-slate-100"
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-[13px] font-bold">Buy Now</span>
                        <ExternalLinkIcon className="h-3.5 w-3.5 text-slate-500" />
                      </div>
                      {item.price && (
                        <span className="text-[12px] font-semibold text-slate-500">
                          {item.price}
                        </span>
                      )}
                    </a>
                  ) : (
                    <div className="flex items-center justify-center rounded-xl border border-white/[0.06] py-2.5 text-[12px] text-slate-600">
                      링크 정보 없음
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
