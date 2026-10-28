"use client";

import { useState } from "react";

export type RequirementOption =
  | string
  | {
      label: string;
      value: string;
      description?: string | null;
    };

type RequirementChoicesProps = {
  question: string;
  options: RequirementOption[];
  onSelect: (option: RequirementOption) => void;
  disabled?: boolean;
  // true면 체크박스로 여러 개를 고른 뒤 "선택 완료"를 눌러야 확정된다(예: 판매처 복수 비교).
  // false/미지정이면 기존처럼 클릭 즉시 확정된다.
  multiSelect?: boolean;
};

function optionKey(option: RequirementOption): string {
  return typeof option === "string" ? option : option.value;
}

function optionLabel(option: RequirementOption): string {
  return typeof option === "string" ? option : option.label;
}

export default function RequirementChoices({
  question,
  options,
  onSelect,
  disabled = false,
  multiSelect = false,
}: RequirementChoicesProps) {
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());

  const toggleSelection = (option: RequirementOption) => {
    const key = optionKey(option);
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    const chosen = options.filter((option) => selectedKeys.has(optionKey(option)));
    if (chosen.length === 0) return;
    // 백엔드(_resolve_resume)가 자유 텍스트에서 복수 선택을 해석하므로, 별도 포맷 없이
    // 선택된 라벨들을 콤마로 이어붙인 자연어 문자열 하나로 기존 onSelect를 그대로 호출한다.
    const combinedLabel = chosen.map(optionLabel).join(", ");
    onSelect(combinedLabel);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">
          조건 입력
        </p>
      </div>
      <p className="text-[15px] font-semibold leading-snug text-white">{question}</p>
      <div className="grid grid-cols-2 gap-2">
        {options.map((option) => {
          const key = optionKey(option);
          const label = optionLabel(option);
          const description = typeof option === "string" ? null : option.description;
          const isSelected = selectedKeys.has(key);
          return (
          <button
            key={key}
            onClick={() => (multiSelect ? toggleSelection(option) : onSelect(option))}
            disabled={disabled}
            className={`group flex items-center gap-2.5 rounded-xl border px-4 py-3 text-left text-[13px] transition disabled:cursor-not-allowed disabled:opacity-40 ${
              isSelected
                ? "border-blue-500/60 bg-blue-500/[0.12] text-white"
                : "border-white/[0.08] bg-white/[0.03] text-slate-300 hover:border-blue-500/40 hover:bg-blue-500/[0.07] hover:text-white"
            }`}
          >
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center border transition ${
                multiSelect ? "rounded-[4px]" : "rounded-full"
              } ${isSelected ? "border-blue-400 bg-blue-500" : "border-slate-600 group-hover:border-blue-400"}`}
            >
              {multiSelect ? (
                isSelected ? (
                  <svg viewBox="0 0 12 12" className="h-2.5 w-2.5 fill-none stroke-white stroke-[2]">
                    <path d="M2 6l2.5 2.5L10 3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : null
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-transparent transition group-hover:bg-blue-400" />
              )}
            </span>
            <span className="min-w-0">
              <span className="block font-medium">{label}</span>
              {description ? (
                <span className="mt-0.5 block text-[11px] leading-snug text-slate-500 group-hover:text-slate-300">
                  {description}
                </span>
              ) : null}
            </span>
          </button>
          );
        })}
      </div>
      {multiSelect ? (
        <button
          onClick={handleConfirm}
          disabled={disabled || selectedKeys.size === 0}
          className="self-start rounded-lg bg-blue-500 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-30"
        >
          선택 완료{selectedKeys.size > 0 ? ` (${selectedKeys.size})` : ""}
        </button>
      ) : null}
    </div>
  );
}
