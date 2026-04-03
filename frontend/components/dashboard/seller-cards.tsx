"use client";

import { BackgroundGradient } from "@/components/ui/background-gradient";

type SellerItem = {
  name: string;
  description: string;
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

const StoreIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="9 22 9 12 15 12 15 22" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function SellerCards({ sellers }: SellerCardsProps) {
  if (!sellers || sellers.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium text-slate-400 tracking-wide px-1">추천 판매처 목록</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 items-stretch">
        {sellers.map((seller, idx) => (
          <BackgroundGradient
            key={idx}
            containerClassName="h-full"
            className="rounded-[22px] bg-[#1a1b20] p-4 flex flex-col gap-3 h-full"
          >
            {/* 번호 배지 + 스토어 아이콘 */}
            <div className="flex items-center justify-between">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-white">
                {idx + 1}
              </span>
              <StoreIcon className="h-4 w-4 text-slate-400" />
            </div>

            {/* 판매처명 */}
            <h3 className="text-sm font-semibold leading-snug text-white">{seller.name}</h3>

            {/* 설명 */}
            <p className="text-xs leading-relaxed text-slate-400 flex-1">{seller.description}</p>

            {/* 방문 링크 */}
            {seller.url && (
              <a
                href={seller.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-auto flex items-center justify-center gap-1.5 rounded-xl bg-white/10 px-3 py-2 text-xs font-medium text-white transition hover:bg-white/20"
              >
                <ExternalLinkIcon className="h-3.5 w-3.5" />
                판매처 방문하기
              </a>
            )}
          </BackgroundGradient>
        ))}
      </div>
    </div>
  );
}
