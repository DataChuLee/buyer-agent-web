"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/auth-provider";
import HistorySidebar from "@/components/dashboard/history-sidebar";
import DashboardNavbar from "@/components/dashboard/navbar";
import AnalysisCards from "@/components/dashboard/analysis-cards";
import ProductCards from "@/components/dashboard/product-cards";
import SellerCards from "@/components/dashboard/seller-cards";
import PromptArea from "@/components/dashboard/prompt-area";
import RequirementChoices from "@/components/dashboard/requirement-choices";
import AgentProgress, { AgentStep } from "@/components/dashboard/agent-progress";
import { cn } from "@/lib/utils";

type ProductItem = {
  name: string;
  features: string;
  recommendation: string;
  price?: string | null;
  url?: string | null;
};

type SellerItem = {
  name: string;
  description: string;
  url?: string | null;
};

type AnalysisItem = {
  name: string;
  seller?: string | null;
  price?: string | null;
  size?: string | null;
  features: string[];
  image?: string | null;
  url?: string | null;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  options?: string[] | null;
  products?: ProductItem[] | null;
  sellers?: SellerItem[] | null;
  analysis?: AnalysisItem[] | null;
  pending?: boolean;
  error?: boolean;
  progressSteps?: AgentStep[] | null;
};

type QuestionItem = {
  key: string;
  question: string;
  options: string[];
};

type ChatConversation = {
  id: string;
  title: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const HISTORY_STORAGE_KEY = "buyer-agent:chat-history";
const ACTIVE_CONVERSATION_STORAGE_KEY = "buyer-agent:active-conversation";
const DISCLAIMER_TEXT =
  "Buyer Agent\uB294 \uC2E4\uC218\uB97C \uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uC911\uC694\uD55C \uC815\uBCF4\uB294 \uC7AC\uCC28 \uD655\uC778\uD558\uC138\uC694.";

function getConversationTitle(message: string) {
  const trimmedMessage = message.trim();

  if (!trimmedMessage) {
    return "New chat";
  }

  if (trimmedMessage.length <= 40) {
    return trimmedMessage;
  }

  return `${trimmedMessage.slice(0, 40).trimEnd()}...`;
}

function buildStorageKey(prefix: string, userId: string) {
  return `${prefix}:${userId}`;
}

function sortConversations(conversations: ChatConversation[]) {
  return [...conversations].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { loading, isAuthenticated, user, signOut } = useAuth();
  const [pendingSignOut, setPendingSignOut] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState(false);
  const [questionSequence, setQuestionSequence] = useState<QuestionItem[] | null>(null);
  const [collectedConditions, setCollectedConditions] = useState<Record<string, string>>({});
  const abortControllerRef = useRef<AbortController | null>(null);
  const [isDesktopViewport, setIsDesktopViewport] = useState(false);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const activeConversation =
    conversations.find((conversation) => conversation.id === activeConversationId) ?? null;
  const chatMessages = activeConversation?.messages ?? [];
  const hasConversation = chatMessages.length > 0;

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (loading) {
      return;
    }

    if (!user?.id) {
      setConversations([]);
      setActiveConversationId(null);
      setHistoryReady(true);
      return;
    }

    const historyStorageKey = buildStorageKey(HISTORY_STORAGE_KEY, user.id);
    const activeStorageKey = buildStorageKey(ACTIVE_CONVERSATION_STORAGE_KEY, user.id);

    try {
      const rawHistory = window.localStorage.getItem(historyStorageKey);
      const parsedHistory = rawHistory ? (JSON.parse(rawHistory) as ChatConversation[]) : [];
      const sortedHistory = Array.isArray(parsedHistory) ? sortConversations(parsedHistory) : [];
      const savedConversationId = window.localStorage.getItem(activeStorageKey);
      const nextActiveConversationId =
        savedConversationId && sortedHistory.some((conversation) => conversation.id === savedConversationId)
          ? savedConversationId
          : sortedHistory[0]?.id ?? null;

      setConversations(sortedHistory);
      setActiveConversationId(nextActiveConversationId);
    } catch {
      setConversations([]);
      setActiveConversationId(null);
    } finally {
      setHistoryReady(true);
    }
  }, [loading, user?.id]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 1024px)");
    const syncViewportState = () => {
      setIsDesktopViewport(mediaQuery.matches);
    };

    syncViewportState();
    mediaQuery.addEventListener("change", syncViewportState);
    return () => {
      mediaQuery.removeEventListener("change", syncViewportState);
    };
  }, []);

  useEffect(() => {
    if (!historyReady || !user?.id) {
      return;
    }

    const historyStorageKey = buildStorageKey(HISTORY_STORAGE_KEY, user.id);
    const activeStorageKey = buildStorageKey(ACTIVE_CONVERSATION_STORAGE_KEY, user.id);

    window.localStorage.setItem(historyStorageKey, JSON.stringify(conversations));

    if (activeConversationId) {
      window.localStorage.setItem(activeStorageKey, activeConversationId);
      return;
    }

    window.localStorage.removeItem(activeStorageKey);
  }, [activeConversationId, conversations, historyReady, user?.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeConversation?.updatedAt, activeConversationId]);

  useEffect(() => {
    if (!mobileSidebarOpen) {
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileSidebarOpen(false);
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
    };
  }, [mobileSidebarOpen]);

  const handleSignOut = async () => {
    try {
      setAuthError(null);
      setPendingSignOut(true);
      await signOut();
      router.replace("/");
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Failed to sign out.");
      setPendingSignOut(false);
    }
  };

  const handleCreateConversation = () => {
    setActiveConversationId(null);
    setMobileSidebarOpen(false);
  };

  const handleSelectConversation = (conversationId: string) => {
    setActiveConversationId(conversationId);
    setMobileSidebarOpen(false);
  };

  const handleToggleSidebar = () => {
    if (isDesktopViewport) {
      setDesktopSidebarOpen((prev) => !prev);
      return;
    }

    setMobileSidebarOpen((prev) => !prev);
  };

  const handleCloseSidebar = () => {
    if (isDesktopViewport) {
      setDesktopSidebarOpen(false);
      return;
    }

    setMobileSidebarOpen(false);
  };

  const handleDeleteConversation = (conversationId: string) => {
    setConversations((prev) => {
      const nextConversations = prev.filter((conversation) => conversation.id !== conversationId);

      setActiveConversationId((currentId) => {
        if (currentId !== conversationId) {
          return currentId;
        }

        return nextConversations[0]?.id ?? null;
      });

      return nextConversations;
    });
  };

  if (loading || !historyReady) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#0e1016]">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-blue-400" />
          <p className="text-[13px] text-slate-500">불러오는 중...</p>
        </div>
      </main>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  const handlePromptSubmit = async (payload: {
    message: string;
    imagePreview: string | null;
    selectedTool: string | null;
  }) => {
    const userMessage = payload.message.trim();
    if (!userMessage) {
      return;
    }

    const conversationId = activeConversationId ?? crypto.randomUUID();
    const timestamp = new Date().toISOString();
    const userMessageId = crypto.randomUUID();
    const assistantMessageId = crypto.randomUUID();

    setConversations((prev) => {
      const existingConversation = prev.find((conversation) => conversation.id === conversationId);
      const nextConversation: ChatConversation = {
        id: conversationId,
        title:
          existingConversation && existingConversation.messages.length > 0
            ? existingConversation.title
            : getConversationTitle(userMessage),
        updatedAt: timestamp,
        messages: [
          ...(existingConversation?.messages ?? []),
          { id: userMessageId, role: "user", content: userMessage },
          { id: assistantMessageId, role: "assistant", content: "", pending: true, progressSteps: [] },
        ],
      };

      return sortConversations([
        nextConversation,
        ...prev.filter((conversation) => conversation.id !== conversationId),
      ]);
    });
    setActiveConversationId(conversationId);
    setMobileSidebarOpen(false);
    setPendingPrompt(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch("/api/buyer-agent/product-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: userMessage,
          user_id: user?.id ?? "anonymous",
          session_id: conversationId,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text();
        let detail = "Product search request failed.";
        try { detail = (JSON.parse(text) as { detail?: string }).detail ?? detail; } catch { /* ignore */ }
        throw new Error(detail);
      }

      if (!response.body) throw new Error("No response body");

      // SSE 스트림 읽기
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let receivedDone = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          let event: {
            type: string;
            chunk?: string;
            message?: string;
            response?: string;
            options?: string[] | null;
            question_sequence?: QuestionItem[] | null;
            products?: ProductItem[] | null;
            sellers?: SellerItem[] | null;
            analysis?: AnalysisItem[] | null;
          };
          try {
            event = JSON.parse(part.slice(6).trim()) as typeof event;
          } catch { continue; }

          if (event.type === "stream" && typeof event.chunk === "string") {
            const chunk = event.chunk;
            setConversations((prev) =>
              sortConversations(
                prev.map((conversation) =>
                  conversation.id === conversationId
                    ? {
                        ...conversation,
                        messages: conversation.messages.map((message) =>
                          message.id === assistantMessageId
                            ? {
                                ...message,
                                content: (message.content ?? "") + chunk,
                                progressSteps: null, // 스트리밍 시작 시 progress 숨김
                              }
                            : message
                        ),
                      }
                    : conversation
                )
              )
            );
          } else if (event.type === "progress" && event.message) {
            // 이전 in-progress 스텝을 completed로 바꾸고 새 스텝 추가
            setConversations((prev) =>
              sortConversations(
                prev.map((conversation) =>
                  conversation.id === conversationId
                    ? {
                        ...conversation,
                        messages: conversation.messages.map((message) =>
                          message.id === assistantMessageId
                            ? {
                                ...message,
                                progressSteps: [
                                  ...(message.progressSteps ?? []).map((s) =>
                                    s.status === "in-progress" ? { ...s, status: "completed" as const } : s
                                  ),
                                  { id: crypto.randomUUID(), message: event.message!, status: "in-progress" as const },
                                ],
                              }
                            : message
                        ),
                      }
                    : conversation
                )
              )
            );
          } else if (event.type === "done") {
            receivedDone = true;
            const assistantReply =
              event.response?.trim() && event.response.trim().length > 0
                ? event.response.trim()
                : "답변을 생성할 수 없습니다.";

            setConversations((prev) =>
              sortConversations(
                prev.map((conversation) =>
                  conversation.id === conversationId
                    ? {
                        ...conversation,
                        updatedAt: new Date().toISOString(),
                        messages: conversation.messages.map((message) =>
                          message.id === assistantMessageId
                            ? {
                                ...message,
                                content: assistantReply,
                                options: event.options ?? null,
                                products: event.products ?? null,
                                sellers: event.sellers ?? null,
                                analysis: event.analysis ?? null,
                                pending: false,
                                progressSteps: null,
                              }
                            : message
                        ),
                      }
                    : conversation
                )
              )
            );

            // 질문 시퀀스가 있으면 로컬 조건 수집 모드 진입
            if (event.question_sequence && event.question_sequence.length > 0) {
              setQuestionSequence(event.question_sequence);
              setCollectedConditions({});
            }
          } else if (event.type === "error") {
            throw new Error(event.message ?? "Agent error");
          }
        }
      }

      if (!receivedDone) {
        throw new Error("응답이 완료되지 않았습니다.");
      }
    } catch (err) {
      const isAborted = err instanceof Error && err.name === "AbortError";
      const errorMessage = isAborted
        ? "요청이 취소되었습니다."
        : err instanceof Error
          ? err.message
          : "Failed to reach backend.";
      setConversations((prev) =>
        sortConversations(
          prev.map((conversation) =>
            conversation.id === conversationId
              ? {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  messages: conversation.messages.map((message) =>
                    message.id === assistantMessageId
                      ? { ...message, content: errorMessage, pending: false, error: !isAborted }
                      : message
                  ),
                }
              : conversation
          )
        )
      );
    } finally {
      setPendingPrompt(false);
      abortControllerRef.current = null;
    }
  };

  // 로컬 조건 수집: 옵션 선택 시 채팅 메시지 없이 다음 질문으로만 전환
  // 모든 조건 선택 완료 시 한 번에 자동 API 호출
  const handleConditionSelect = (option: string) => {
    if (!questionSequence || questionSequence.length === 0) return;

    const currentKey = questionSequence[0].key;
    const newConditions = { ...collectedConditions, [currentKey]: option };
    const remaining = questionSequence.slice(1);

    if (remaining.length > 0) {
      // 다음 질문이 있으면 현재 질문 카드를 다음 질문으로 교체 (새 메시지 추가 없음)
      setConversations((prev) =>
        sortConversations(
          prev.map((conversation) => {
            if (conversation.id !== activeConversationId) return conversation;
            const messages = conversation.messages.map((msg) =>
              msg.role === "assistant" && msg.options
                ? { ...msg, content: remaining[0].question, options: remaining[0].options }
                : msg
            );
            return { ...conversation, updatedAt: new Date().toISOString(), messages };
          })
        )
      );
      setQuestionSequence(remaining);
      setCollectedConditions(newConditions);
    } else {
      // 모든 조건 수집 완료 → 질문 카드 제거 후 자동 API 호출
      setConversations((prev) =>
        sortConversations(
          prev.map((conversation) => {
            if (conversation.id !== activeConversationId) return conversation;
            const messages = conversation.messages.map((msg) =>
              msg.role === "assistant" && msg.options ? { ...msg, options: null } : msg
            );
            return { ...conversation, messages };
          })
        )
      );
      setQuestionSequence(null);
      setCollectedConditions({});
      const conditionMessage = Object.values(newConditions).join(" ");
      handlePromptSubmit({ message: conditionMessage, imagePreview: null, selectedTool: null });
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#0e1016] text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.04),transparent_60%)]" />
      <div className="relative z-10 flex min-h-screen w-full">
        <HistorySidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          isDesktopOpen={desktopSidebarOpen}
          isMobileOpen={mobileSidebarOpen}
          onClose={handleCloseSidebar}
          onToggleSidebar={handleToggleSidebar}
          onCreateConversation={handleCreateConversation}
          onDeleteConversation={handleDeleteConversation}
          onSelectConversation={handleSelectConversation}
        />

        <div className="flex min-h-screen min-w-0 flex-1 flex-col px-3 pb-8 pt-0 md:px-6 lg:px-8">
          <DashboardNavbar
            user={user}
            pendingSignOut={pendingSignOut}
            onSignOut={handleSignOut}
            onToggleSidebar={handleToggleSidebar}
            isSidebarOpen={isDesktopViewport ? desktopSidebarOpen : mobileSidebarOpen}
            isDesktopViewport={isDesktopViewport}
          />

          <section className="flex min-h-0 flex-1">
            {!hasConversation ? (
              /* ── Empty state ── */
              <div
                className={cn(
                  "pointer-events-none fixed bottom-0 right-0 top-16 z-10 flex flex-col items-center justify-center gap-6 px-4 pb-44",
                  isDesktopViewport ? (desktopSidebarOpen ? "lg:left-72" : "lg:left-[60px]") : "left-0"
                )}
              >
                {/* Icon */}
                <div className="flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/20 to-violet-500/20 ring-1 ring-white/10">
                  <svg className="h-8 w-8 text-blue-400" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M8 44 C8 44 14 28 28 24 C36 22 46 26 52 22 C56 20 58 16 58 16" />
                    <path d="M8 44 C8 44 10 50 16 52 C22 54 30 52 36 50 C44 48 52 48 56 44 C60 40 58 34 52 32 C46 30 38 34 30 36 C20 38 12 36 8 44Z" fill="currentColor" fillOpacity="0.08" />
                    <circle cx="22" cy="40" r="2.5" fill="currentColor" />
                    <circle cx="34" cy="37" r="2.5" fill="currentColor" />
                    <circle cx="44" cy="40" r="2.5" fill="currentColor" />
                  </svg>
                </div>

                {/* Headline */}
                <div className="text-center">
                  <h1 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
                    어떤 축구화를 찾고 계세요?
                  </h1>
                  <p className="mt-2 text-[15px] text-slate-500">
                    축구화 · 풋살화를 자유롭게 말해주세요
                  </p>
                </div>

                {/* Suggestion chips */}
                <div className="pointer-events-auto flex flex-wrap justify-center gap-2">
                  {[
                    "가성비 좋은 축구화 추천해줘",
                    "10만원대 풋살화 비교해줘",
                    "나이키 머큐리얼 최저가 찾아줘",
                    "아디다스 프레데터 vs 나이키 팬텀",
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() =>
                        handlePromptSubmit({ message: suggestion, imagePreview: null, selectedTool: null })
                      }
                      className="rounded-full border border-white/[0.09] bg-white/[0.04] px-4 py-2 text-[13px] text-slate-400 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              /* ── Chat messages ── */
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex-1 overflow-y-auto pb-44 pt-6">
                  <div className="mx-auto w-full max-w-3xl space-y-6 px-2">
                    {chatMessages.map((message) => (
                      <div
                        key={message.id}
                        className={`flex items-end gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        {/* Agent avatar */}
                        {message.role === "assistant" && (
                          <div className="mb-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 shadow-md">
                            <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2v-4M9 21H5a2 2 0 0 1-2-2v-4m0 0h18" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          </div>
                        )}

                        <div className={message.role === "user" ? "max-w-[78%] md:max-w-[65%]" : "min-w-0 max-w-[84%]"}>
                          {message.role === "user" ? (
                            <div className="rounded-2xl rounded-br-md bg-white/[0.1] px-4 py-3 text-[15px] leading-relaxed text-white ring-1 ring-white/[0.06]">
                              {message.content}
                            </div>
                          ) : message.pending && message.progressSteps !== null ? (
                            <div className="rounded-2xl rounded-bl-md bg-white/[0.04] px-4 py-3 ring-1 ring-white/[0.06]">
                              <AgentProgress steps={message.progressSteps ?? []} />
                            </div>
                          ) : message.pending ? (
                            <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-white/90">
                              {message.content}
                              <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-white/60 align-middle" />
                            </div>
                          ) : message.options && message.options.length > 0 ? (
                            <RequirementChoices
                              question={message.content}
                              options={message.options}
                              onSelect={questionSequence ? handleConditionSelect : (option) =>
                                handlePromptSubmit({ message: option, imagePreview: null, selectedTool: null })
                              }
                              disabled={pendingPrompt}
                            />
                          ) : message.products && message.products.length > 0 ? (
                            <div className="w-full">
                              <ProductCards products={message.products} />
                            </div>
                          ) : message.sellers && message.sellers.length > 0 ? (
                            <div className="w-full">
                              <SellerCards sellers={message.sellers} />
                            </div>
                          ) : message.analysis && message.analysis.length > 0 ? (
                            <div className="w-full">
                              <AnalysisCards analysis={message.analysis} />
                            </div>
                          ) : (
                            <div
                              className={`whitespace-pre-wrap text-[15px] leading-relaxed ${
                                message.error
                                  ? "rounded-xl bg-rose-500/10 px-4 py-3 text-rose-300 ring-1 ring-rose-500/20"
                                  : "text-white/90"
                              }`}
                            >
                              {message.content}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>
                </div>
              </div>
            )}

            <div
              className={cn(
                "pointer-events-none fixed bottom-0 right-0 z-20 bg-gradient-to-t from-[#0e1016] via-[#0e1016]/90 to-transparent px-3 pb-3 pt-8 md:px-6 lg:px-8",
                isDesktopViewport ? (desktopSidebarOpen ? "lg:left-72" : "lg:left-[60px]") : "left-0"
              )}
            >
              <div className="pointer-events-auto mx-auto w-full max-w-5xl">
                <PromptArea
                  mode={hasConversation ? "chat" : "hero"}
                  isSubmitting={pendingPrompt}
                  onSubmit={handlePromptSubmit}
                  onStop={handleStop}
                />
              </div>
              {hasConversation ? <p className="mt-3 text-center text-xs text-slate-400">{DISCLAIMER_TEXT}</p> : null}
              {authError ? <p className="mt-3 text-center text-sm text-rose-400">{authError}</p> : null}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
