"use client";

import { useRef, useState } from "react";

interface PromptAreaProps {
  mode?: "hero" | "chat";
  placeholder?: string;
  isSubmitting?: boolean;
  onSubmit?: (payload: {
    message: string;
    imagePreview: string | null;
    selectedTool: string | null;
  }) => void | Promise<void>;
}

const PlusIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M12 5v14" strokeLinecap="round" />
    <path d="M5 12h14" strokeLinecap="round" />
  </svg>
);

const SendIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <path d="M12 5.25v13.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18.75 12 12 5.25 5.25 12" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const StopIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <rect x="7.5" y="7.5" width="9" height="9" rx="1.5" />
  </svg>
);

const XIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <line x1="18" y1="6" x2="6" y2="18" strokeLinecap="round" />
    <line x1="6" y1="6" x2="18" y2="18" strokeLinecap="round" />
  </svg>
);

const MicIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
    <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
    <path d="M12 18v4" />
  </svg>
);

export default function PromptArea({
  mode = "chat",
  placeholder = "원하는 제품과 예산, 조건을 알려주세요",
  isSubmitting = false,
  onSubmit,
}: PromptAreaProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [value, setValue] = useState("");
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const hasValue = value.trim().length > 0;

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !file.type.startsWith("image/")) {
      event.target.value = "";
      return;
    }

    const reader = new FileReader();
    reader.onloadend = () => {
      setImagePreview(reader.result as string);
    };
    reader.readAsDataURL(file);
    event.target.value = "";
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hasValue || isSubmitting) {
      return;
    }
    onSubmit?.({
      message: value.trim(),
      imagePreview,
      selectedTool: null,
    });
    setValue("");
    setImagePreview(null);
  };

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <form onSubmit={handleSubmit} className={`w-full ${mode === "hero" ? "max-w-5xl" : ""}`}>
      <div className="relative">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleFileChange}
        />

        {imagePreview ? (
          <div className="mb-3 flex">
            <div className="relative inline-flex rounded-xl border border-white/20 bg-white/5 p-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imagePreview} alt="Uploaded preview" className="h-14 w-14 rounded-lg object-cover" />
              <button
                type="button"
                onClick={() => setImagePreview(null)}
                className="absolute -right-2 -top-2 rounded-full border border-white/25 bg-black/80 p-1 text-white transition hover:bg-black"
                aria-label="Remove image"
              >
                <XIcon className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ) : null}

        <div
          className={`flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.07] px-4 py-2.5 shadow-[0_20px_50px_-35px_rgba(0,0,0,0.95)] backdrop-blur-xl ${
            mode === "hero" ? "md:py-3" : ""
          }`}
        >
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white/90 transition hover:bg-white/15"
            aria-label="Attach image"
          >
            <PlusIcon className="h-6 w-6" />
          </button>

          <input
            name="message"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder={placeholder}
            className={`h-10 flex-1 border-0 bg-transparent text-white placeholder:text-slate-400 focus:outline-none ${
              mode === "hero" ? "text-base md:text-lg" : "text-lg"
            }`}
          />

          <button
            type="button"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white/85 transition hover:bg-white/15"
            aria-label="Record voice"
          >
            <MicIcon className="h-5 w-5" />
          </button>

          <button
            type="submit"
            disabled={!hasValue || isSubmitting}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-black transition hover:bg-white/90 disabled:cursor-not-allowed disabled:bg-white/40"
            aria-label="Send message"
          >
            {isSubmitting ? <StopIcon className="h-4 w-4" /> : <SendIcon className="h-5 w-5" />}
          </button>
        </div>
      </div>
    </form>
  );
}
