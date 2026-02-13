"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { BorderBeam } from "@/components/ui/border-beam";

interface PromptAreaProps {
  onSubmit?: (payload: {
    message: string;
    imagePreview: string | null;
    selectedTool: string | null;
  }) => void;
}

type ToolItem = {
  id: string;
  name: string;
  shortName: string;
  extra?: string;
  icon: (props: React.SVGProps<SVGSVGElement>) => React.JSX.Element;
};

const PlusIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M12 5v14" strokeLinecap="round" />
    <path d="M5 12h14" strokeLinecap="round" />
  </svg>
);

const Settings2Icon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M20 7h-9" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M14 17H5" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="17" cy="17" r="3" />
    <circle cx="7" cy="7" r="3" />
  </svg>
);

const SendIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <path d="M12 5.25v13.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18.75 12 12 5.25 5.25 12" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const XIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
    <line x1="18" y1="6" x2="6" y2="18" strokeLinecap="round" />
    <line x1="6" y1="6" x2="18" y2="18" strokeLinecap="round" />
  </svg>
);

const GlobeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <circle cx="12" cy="12" r="10" />
    <path d="M2 12h20" strokeLinecap="round" />
    <path d="M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10 15 15 0 0 1-4-10 15 15 0 0 1 4-10Z" />
  </svg>
);

const PencilIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="m16.5 3.5 4 4L7.5 20.5 2 22l1.5-5.5Z" />
    <path d="m15 5 4 4" />
  </svg>
);

const PaintBrushIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M7 16c-2 0-3.5 1.5-3.5 3.5V22H7a4 4 0 0 0 4-4v-1.5A2.5 2.5 0 0 0 8.5 14H8" />
    <path d="m14.5 3.5 6 6L11 19l-6-6 9.5-9.5Z" />
  </svg>
);

const TelescopeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="m4 8 9 9" />
    <path d="m10 2 12 12-3 3L7 5l3-3Z" />
    <path d="M8 14 3 21h4l3-4" />
  </svg>
);

const LightbulbIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M9.5 16.8 10 19h4l.5-2.2a5.5 5.5 0 1 0-5 0Z" />
    <path d="M10 19h4" strokeLinecap="round" />
  </svg>
);

const MicIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" {...props}>
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
    <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
    <path d="M12 18v4" />
  </svg>
);

const toolsList: ToolItem[] = [
  { id: "create-image", name: "Create an image", shortName: "Image", icon: PaintBrushIcon },
  { id: "search-web", name: "Search the web", shortName: "Search", icon: GlobeIcon },
  { id: "write-code", name: "Write code", shortName: "Write", icon: PencilIcon },
  { id: "deep-research", name: "Run deep research", shortName: "Deep Search", extra: "5 left", icon: TelescopeIcon },
  { id: "think-longer", name: "Think for longer", shortName: "Think", icon: LightbulbIcon },
];

export default function PromptArea({ onSubmit }: PromptAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toolsMenuRef = useRef<HTMLDivElement>(null);

  const [value, setValue] = useState("");
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [isToolMenuOpen, setIsToolMenuOpen] = useState(false);

  useLayoutEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 280)}px`;
  }, [value]);

  useEffect(() => {
    if (!isToolMenuOpen) {
      return;
    }

    const onMouseDown = (event: MouseEvent) => {
      if (!toolsMenuRef.current?.contains(event.target as Node)) {
        setIsToolMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", onMouseDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [isToolMenuOpen]);

  const activeTool = selectedTool ? toolsList.find((tool) => tool.id === selectedTool) : null;
  const ActiveToolIcon = activeTool?.icon;
  const hasValue = value.trim().length > 0 || Boolean(imagePreview);

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
    if (!hasValue) {
      return;
    }
    onSubmit?.({
      message: value.trim(),
      imagePreview,
      selectedTool,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="relative overflow-hidden rounded-[32px] bg-black/55 p-3 shadow-[0_38px_80px_-40px_rgba(0,0,0,1)] backdrop-blur-2xl">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleFileChange}
        />

        {imagePreview ? (
          <div className="relative mb-3 inline-flex rounded-2xl border border-white/20 bg-white/5 p-1">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imagePreview} alt="Uploaded preview" className="h-16 w-16 rounded-xl object-cover" />
            <button
              type="button"
              onClick={() => setImagePreview(null)}
              className="absolute -right-2 -top-2 rounded-full border border-white/20 bg-black/80 p-1 text-white transition hover:bg-black"
              aria-label="Remove image"
            >
              <XIcon className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}

        <textarea
          ref={textareaRef}
          name="message"
          rows={1}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="What do you want to buy today?"
          className="min-h-28 w-full resize-none border-0 bg-transparent px-3 py-4 text-lg text-white placeholder:text-slate-400 focus:outline-none md:min-h-36 md:text-xl"
        />

        <div className="mt-2 flex items-center gap-2 p-1">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex h-10 w-10 items-center justify-center rounded-full text-white transition hover:bg-white/15"
            aria-label="Attach image"
          >
            <PlusIcon className="h-6 w-6" />
          </button>

          <div ref={toolsMenuRef} className="relative">
            <button
              type="button"
              onClick={() => setIsToolMenuOpen((prev) => !prev)}
              className="flex h-10 items-center gap-2 rounded-full px-3 text-sm text-white transition hover:bg-white/15"
            >
              <Settings2Icon className="h-4 w-4" />
              {!activeTool ? "Tools" : activeTool.shortName}
            </button>

            <div
              className={cn(
                "absolute bottom-full left-0 mb-2 w-64 rounded-2xl border border-white/20 bg-[#10151f]/95 p-2 shadow-xl backdrop-blur-xl transition",
                isToolMenuOpen ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-1 opacity-0"
              )}
            >
              {toolsList.map((tool) => (
                <button
                  key={tool.id}
                  type="button"
                  onClick={() => {
                    setSelectedTool(tool.id);
                    setIsToolMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-slate-100 transition hover:bg-white/10"
                >
                  <tool.icon className="h-4 w-4" />
                  <span>{tool.name}</span>
                  {tool.extra ? <span className="ml-auto text-xs text-slate-400">{tool.extra}</span> : null}
                </button>
              ))}
            </div>
          </div>

          {activeTool ? (
            <button
              type="button"
              onClick={() => setSelectedTool(null)}
              className="flex h-10 items-center gap-2 rounded-full border border-sky-400/40 bg-sky-500/10 px-3 text-sm text-sky-200 transition hover:bg-sky-500/20"
            >
              {ActiveToolIcon ? <ActiveToolIcon className="h-4 w-4" /> : null}
              {activeTool.shortName}
              <XIcon className="h-4 w-4" />
            </button>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="flex h-10 w-10 items-center justify-center rounded-full text-white transition hover:bg-white/15"
              aria-label="Record voice"
            >
              <MicIcon className="h-5 w-5" />
            </button>
            <button
              type="submit"
              disabled={!hasValue}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-black transition hover:bg-white/85 disabled:cursor-not-allowed disabled:bg-white/30 disabled:text-black/50"
              aria-label="Send message"
            >
              <SendIcon className="h-5 w-5" />
            </button>
          </div>
        </div>

        <BorderBeam
          duration={5}
          colorFrom="#22c55e"
          colorTo="#ffffff"
          borderWidth={1.5}
        />
      </div>
    </form>
  );
}
