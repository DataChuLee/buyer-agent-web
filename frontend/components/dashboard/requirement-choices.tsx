"use client";

type RequirementChoicesProps = {
  question: string;
  options: string[];
  onSelect: (option: string) => void;
  disabled?: boolean;
};

export default function RequirementChoices({
  question,
  options,
  onSelect,
  disabled = false,
}: RequirementChoicesProps) {
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
        {options.map((option) => (
          <button
            key={option}
            onClick={() => onSelect(option)}
            disabled={disabled}
            className="group flex items-center gap-2.5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-left text-[13px] text-slate-300 transition hover:border-blue-500/40 hover:bg-blue-500/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-slate-600 transition group-hover:border-blue-400">
              <span className="h-1.5 w-1.5 rounded-full bg-transparent transition group-hover:bg-blue-400" />
            </span>
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}
