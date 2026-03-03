"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

interface HistoryConversation {
  id: string;
  title: string;
  updatedAt: string;
  messages: HistoryMessage[];
}

interface HistorySidebarProps {
  conversations: HistoryConversation[];
  activeConversationId: string | null;
  isDesktopOpen: boolean;
  isMobileOpen: boolean;
  onClose: () => void;
  onToggleSidebar: () => void;
  onCreateConversation: () => void;
  onDeleteConversation: (conversationId: string) => void;
  onSelectConversation: (conversationId: string) => void;
}

const ChevronLeftIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <path d="m15 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SidebarToggleIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <rect x="3.5" y="5" width="17" height="14" rx="2" />
    <path d="M9 5v14" strokeLinecap="round" />
  </svg>
);

const ComposeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <path d="m4 20 4.5-1 9-9a2.1 2.1 0 0 0-3-3l-9 9L4 20Z" strokeLinecap="round" strokeLinejoin="round" />
    <path d="m13.5 7.5 3 3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const HistoryIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <path d="M4 12a8 8 0 1 0 2.3-5.7" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4 4v4h4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M12 8v4l2.5 1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const TrashIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <path d="M4 7h16" strokeLinecap="round" />
    <path d="M10 11v6" strokeLinecap="round" />
    <path d="M14 11v6" strokeLinecap="round" />
    <path d="M6 7l1 11a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-11" />
    <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
  </svg>
);

function formatUpdatedAt(updatedAt: string) {
  const date = new Date(updatedAt);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const dayMs = 24 * 60 * 60 * 1000;

  if (diff < dayMs) {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  if (diff < dayMs * 7) {
    return new Intl.DateTimeFormat("en-US", {
      weekday: "short",
    }).format(date);
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function getPreview(messages: HistoryMessage[]) {
  const latestMessage = [...messages].reverse().find((message) => message.content.trim().length > 0);
  if (!latestMessage) {
    return "Start a new search";
  }

  return latestMessage.content;
}

function truncate(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength).trimEnd()}...`;
}

function CompactActionButton({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative inline-flex h-11 w-11 items-center justify-center rounded-2xl text-slate-300 transition hover:bg-white/10 hover:text-white"
      aria-label={label}
    >
      {icon}
      <span className="pointer-events-none absolute left-full top-1/2 z-10 ml-3 -translate-y-1/2 whitespace-nowrap rounded-xl bg-black px-3 py-1.5 text-xs font-medium text-white opacity-0 shadow-lg transition group-hover:opacity-100">
        {label}
      </span>
    </button>
  );
}

export default function HistorySidebar({
  conversations,
  activeConversationId,
  isDesktopOpen,
  isMobileOpen,
  onClose,
  onToggleSidebar,
  onCreateConversation,
  onDeleteConversation,
  onSelectConversation,
}: HistorySidebarProps) {
  const isCollapsed = !isDesktopOpen && !isMobileOpen;

  return (
    <>
      <button
        type="button"
        aria-label="Close history sidebar"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-20 bg-black/55 backdrop-blur-sm transition lg:hidden",
          isMobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex shrink-0 flex-col overflow-hidden border-r border-white/10 bg-[#111318]/95 shadow-[0_24px_60px_-32px_rgba(0,0,0,0.95)] backdrop-blur-xl transition-[width,transform,padding] duration-300",
          isMobileOpen ? "w-72 translate-x-0 px-3 py-4" : "w-72 -translate-x-full px-3 py-4",
          isDesktopOpen ? "lg:w-72 lg:translate-x-0 lg:px-3" : "lg:w-16 lg:translate-x-0 lg:px-2",
          "lg:static lg:bg-white/[0.03] lg:shadow-none"
        )}
      >
        {isCollapsed ? (
          <div className="hidden h-full flex-col items-center gap-3 lg:flex">
            <CompactActionButton
              icon={<SidebarToggleIcon className="h-5 w-5" />}
              label="사이드바 열기"
              onClick={onToggleSidebar}
            />
            <CompactActionButton
              icon={<ComposeIcon className="h-5 w-5" />}
              label="새 채팅"
              onClick={onCreateConversation}
            />
            <CompactActionButton
              icon={<HistoryIcon className="h-5 w-5" />}
              label="대화 기록"
              onClick={onToggleSidebar}
            />
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-2">
              <Link href="/" className="flex items-center gap-3 text-white transition hover:opacity-80">
                <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-white/10 text-sm font-bold">
                  BA
                </span>
                <span className="text-lg font-semibold tracking-wide">Buyer Agent</span>
              </Link>
              <button
                type="button"
                onClick={onToggleSidebar}
                className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-white/[0.08] text-slate-300 transition hover:bg-white/[0.12] hover:text-white"
                aria-label={isMobileOpen ? "사이드바 닫기" : "사이드바 접기"}
                title={isMobileOpen ? "사이드바 닫기" : "사이드바 접기"}
              >
                {isMobileOpen ? <ChevronLeftIcon className="h-5 w-5" /> : <SidebarToggleIcon className="h-5 w-5" />}
              </button>
            </div>

            <button
              type="button"
              onClick={onCreateConversation}
              className="mt-5 inline-flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.06] px-4 py-3 text-sm font-medium text-white transition hover:bg-white/[0.1]"
            >
              <ComposeIcon className="h-4 w-4" />
              New chat
            </button>

            <div className="mt-6 flex items-center justify-between px-2">
              <p className="text-xs tracking-[0.28em] text-slate-500">채팅</p>
              <span className="text-xs text-slate-500">{conversations.length}</span>
            </div>

            <div className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
              {conversations.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] px-4 py-5 text-sm leading-relaxed text-slate-400">
                  Your searches will appear here. Start a conversation to build the list.
                </div>
              ) : (
                conversations.map((conversation) => {
                  const isActive = conversation.id === activeConversationId;

                  return (
                    <div
                      key={conversation.id}
                      className={cn(
                        "group rounded-2xl border border-transparent transition",
                        isActive ? "border-sky-400/30 bg-sky-400/10" : "bg-white/[0.03] hover:bg-white/[0.06]"
                      )}
                    >
                      <div className="px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <button
                            type="button"
                            onClick={() => onSelectConversation(conversation.id)}
                            className="min-w-0 flex-1 text-left"
                          >
                            <p className="truncate text-sm font-medium text-white">{conversation.title}</p>
                            <p className="mt-1 text-xs text-slate-400">{formatUpdatedAt(conversation.updatedAt)}</p>
                          </button>
                          <button
                            type="button"
                            onClick={() => onDeleteConversation(conversation.id)}
                            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-slate-500 opacity-0 transition hover:bg-white/10 hover:text-white group-hover:opacity-100 focus-visible:opacity-100"
                            aria-label={`Delete ${conversation.title}`}
                          >
                            <TrashIcon className="h-4 w-4" />
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => onSelectConversation(conversation.id)}
                          className="mt-3 block w-full text-left text-sm leading-6 text-slate-400"
                        >
                          {truncate(getPreview(conversation.messages), 72)}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </aside>
    </>
  );
}
