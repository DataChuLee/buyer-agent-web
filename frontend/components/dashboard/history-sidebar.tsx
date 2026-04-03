"use client";

import Link from "next/link";
import BrandLogo from "@/components/brand-logo";
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
    return new Intl.DateTimeFormat("ko-KR", {
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  if (diff < dayMs * 7) {
    return new Intl.DateTimeFormat("ko-KR", { weekday: "short" }).format(date);
  }

  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function getPreview(messages: HistoryMessage[]) {
  const latestAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.content.trim().length > 0);
  if (!latestAssistant) return "대화를 시작해보세요";
  return latestAssistant.content;
}

function truncate(value: string, maxLength: number) {
  return value.length <= maxLength ? value : `${value.slice(0, maxLength).trimEnd()}...`;
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
      className="group relative inline-flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 transition hover:bg-white/8 hover:text-white"
      aria-label={label}
    >
      {icon}
      <span className="pointer-events-none absolute left-full top-1/2 z-10 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg bg-zinc-800 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 shadow-xl transition group-hover:opacity-100">
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
      {/* Mobile overlay */}
      <button
        type="button"
        aria-label="사이드바 닫기"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-20 bg-black/60 backdrop-blur-sm transition lg:hidden",
          isMobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex shrink-0 flex-col overflow-hidden border-r border-white/[0.06] bg-[#0e1016]/98 shadow-2xl backdrop-blur-xl transition-[width,transform,padding] duration-300",
          isMobileOpen ? "w-72 translate-x-0 px-3 py-5" : "w-72 -translate-x-full px-3 py-5",
          isDesktopOpen ? "lg:w-72 lg:translate-x-0 lg:px-3 lg:py-5" : "lg:w-[60px] lg:translate-x-0 lg:px-2 lg:py-4",
          "lg:static lg:shadow-none"
        )}
      >
        {/* ── Collapsed rail ── */}
        {isCollapsed ? (
          <div className="hidden h-full flex-col items-center gap-1 pt-1 lg:flex">
            <CompactActionButton
              icon={<SidebarToggleIcon className="h-[18px] w-[18px]" />}
              label="사이드바 열기"
              onClick={onToggleSidebar}
            />
            <CompactActionButton
              icon={<ComposeIcon className="h-[18px] w-[18px]" />}
              label="새 대화"
              onClick={onCreateConversation}
            />
            <div className="my-1 h-px w-6 bg-white/10" />
            <CompactActionButton
              icon={<HistoryIcon className="h-[18px] w-[18px]" />}
              label="대화 기록"
              onClick={onToggleSidebar}
            />
          </div>
        ) : (
          <>
            {/* ── Header ── */}
            <div className="flex items-center justify-between px-1">
              <Link href="/" className="inline-flex items-center gap-2 transition-opacity hover:opacity-70">
                <BrandLogo className="h-8" />
                <span className="text-[13px] font-bold tracking-tight text-white/80">BuyerAgent</span>
              </Link>
              <button
                type="button"
                onClick={onToggleSidebar}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white/8 hover:text-white"
                aria-label={isMobileOpen ? "사이드바 닫기" : "사이드바 접기"}
              >
                {isMobileOpen ? <ChevronLeftIcon className="h-[18px] w-[18px]" /> : <SidebarToggleIcon className="h-[18px] w-[18px]" />}
              </button>
            </div>

            {/* ── New chat button ── */}
            <button
              type="button"
              onClick={onCreateConversation}
              className="mt-4 flex items-center gap-2.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3.5 py-2.5 text-[13px] font-medium text-slate-300 transition hover:border-white/15 hover:bg-white/[0.08] hover:text-white"
            >
              <ComposeIcon className="h-4 w-4 shrink-0" />
              새 대화 시작
            </button>

            {/* ── History label ── */}
            <div className="mt-5 mb-2 flex items-center justify-between px-1">
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-600">최근 대화</p>
              {conversations.length > 0 && (
                <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium text-slate-500">
                  {conversations.length}
                </span>
              )}
            </div>

            {/* ── Conversation list ── */}
            <div className="flex-1 overflow-y-auto space-y-0.5 pr-0.5 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.08)_transparent]">
              {conversations.length === 0 ? (
                <div className="mt-2 rounded-xl border border-dashed border-white/[0.07] px-4 py-5">
                  <p className="text-[13px] leading-relaxed text-slate-500">
                    검색 기록이 여기 표시돼요.
                    <br />
                    새 대화를 시작해보세요.
                  </p>
                </div>
              ) : (
                conversations.map((conversation) => {
                  const isActive = conversation.id === activeConversationId;

                  return (
                    <div
                      key={conversation.id}
                      className={cn(
                        "group relative rounded-xl transition-colors",
                        isActive
                          ? "bg-white/[0.07]"
                          : "hover:bg-white/[0.04]"
                      )}
                    >
                      {isActive && (
                        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-blue-400" />
                      )}
                      <div className="px-3 py-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <button
                            type="button"
                            onClick={() => onSelectConversation(conversation.id)}
                            className="min-w-0 flex-1 text-left"
                          >
                            <p className={cn("truncate text-[13px] font-medium leading-snug", isActive ? "text-white" : "text-slate-300")}>
                              {conversation.title}
                            </p>
                            <p className="mt-0.5 text-[11px] text-slate-600">
                              {formatUpdatedAt(conversation.updatedAt)}
                            </p>
                          </button>
                          <button
                            type="button"
                            onClick={() => onDeleteConversation(conversation.id)}
                            className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-600 opacity-0 transition hover:bg-white/10 hover:text-rose-400 group-hover:opacity-100"
                            aria-label={`${conversation.title} 삭제`}
                          >
                            <TrashIcon className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => onSelectConversation(conversation.id)}
                          className="mt-1.5 block w-full text-left text-[12px] leading-[1.5] text-slate-600 line-clamp-2"
                        >
                          {truncate(getPreview(conversation.messages), 60)}
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
