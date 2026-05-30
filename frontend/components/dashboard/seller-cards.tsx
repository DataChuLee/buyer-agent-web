"use client";

type SellerItem = {
  name: string;
  description: string;
  why_recommended?: string | null;
  url?: string | null;
};

type SellerCardsProps = {
  sellers: SellerItem[];
};

const ExternalLinkIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="15 3 21 3 21 9" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="10" y1="14" x2="21" y2="3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const rankNum = ["01", "02", "03", "04", "05", "06"];

export default function SellerCards({ sellers }: SellerCardsProps) {
  if (!sellers || sellers.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 w-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-1">
        <span className="h-1 w-4 rounded-full bg-emerald-500" />
        <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
          추천 판매처 목록
        </p>
      </div>

      {/* Cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sellers.map((seller, idx) => (
          <div
            key={idx}
            className="group relative flex flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-[#13141a] transition duration-200 hover:border-white/[0.14] hover:bg-[#16171e]"
          >
            <div className="flex flex-1 flex-col gap-2.5 p-4">
              {/* Rank */}
              <span className="font-mono text-[11px] font-bold text-slate-700">
                {rankNum[idx] ?? String(idx + 1).padStart(2, "0")}
              </span>

              {/* Name */}
              <h3 className="text-[14px] font-bold leading-snug text-white">
                {seller.name}
              </h3>

              {/* Description */}
              <ul className="flex flex-1 flex-col gap-1.5">
                {(seller.description ?? "").split(/[.·•\n]/).filter(d => d.trim()).map((line, i) => (
                  <li key={i} className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-400">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-600" />
                    {line.trim()}
                  </li>
                ))}
              </ul>

              {/* Why Recommended */}
              {seller.why_recommended && (
                <div className="mt-1 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2">
                  <p className="mb-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-amber-400/80">
                    추천 이유
                  </p>
                  <p className="text-[12px] leading-relaxed text-amber-200/70">
                    {seller.why_recommended}
                  </p>
                </div>
              )}

              {/* CTA */}
              <div className="mt-auto pt-1">
                {seller.url ? (
                  <a
                    href={seller.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] py-2.5 text-[12px] font-semibold text-slate-300 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white"
                  >
                    <ExternalLinkIcon className="h-3.5 w-3.5" />
                    판매처 방문하기
                  </a>
                ) : (
                  <div className="flex items-center justify-center rounded-xl border border-white/[0.06] py-2.5 text-[12px] text-slate-600">
                    링크 정보 없음
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
