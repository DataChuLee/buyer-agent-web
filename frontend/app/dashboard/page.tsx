"use client";

import { useEffect, useRef, useState } from "react";
import { Indie_Flower } from "next/font/google";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/auth-provider";
import HistorySidebar from "@/components/dashboard/history-sidebar";
import DashboardNavbar from "@/components/dashboard/navbar";
import PromptArea from "@/components/dashboard/prompt-area";
import { cn } from "@/lib/utils";

const indieFlower = Indie_Flower({
  subsets: ["latin"],
  weight: "400",
});

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  error?: boolean;
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
      <main className="flex min-h-screen items-center justify-center bg-[#181818] text-slate-200">
        Loading dashboard...
      </main>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

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
          { id: assistantMessageId, role: "assistant", content: "Thinking...", pending: true },
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

    try {
      const response = await fetch("/api/buyer-agent/product-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: userMessage }),
      });
      const text = await response.text();
      let data: { response?: string; detail?: string } = {};
      if (text) {
        try {
          data = JSON.parse(text) as { response?: string; detail?: string };
        } catch {
          data = { detail: text };
        }
      }

      if (!response.ok) {
        throw new Error(data.detail ?? "Product search request failed.");
      }

      const assistantReply =
        data.response?.trim() && data.response.trim().length > 0
          ? data.response.trim()
          : "I could not generate an answer right now.";

      setConversations((prev) =>
        sortConversations(
          prev.map((conversation) =>
            conversation.id === conversationId
              ? {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  messages: conversation.messages.map((message) =>
                    message.id === assistantMessageId
                      ? { ...message, content: assistantReply, pending: false }
                      : message
                  ),
                }
              : conversation
          )
        )
      );
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to reach backend.";
      setConversations((prev) =>
        sortConversations(
          prev.map((conversation) =>
            conversation.id === conversationId
              ? {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  messages: conversation.messages.map((message) =>
                    message.id === assistantMessageId
                      ? { ...message, content: errorMessage, pending: false, error: true }
                      : message
                  ),
                }
              : conversation
          )
        )
      );
    } finally {
      setPendingPrompt(false);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#1f2025] text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.06),transparent_40%)]" />
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
              <div
                className={cn(
                  "pointer-events-none fixed bottom-0 right-0 top-20 z-10 flex items-center justify-center px-4 pb-36",
                  isDesktopViewport ? (desktopSidebarOpen ? "lg:left-72" : "lg:left-16") : "left-0"
                )}
              >
                <h1
                  className={`${indieFlower.className} text-center text-4xl tracking-tight text-white md:text-5xl`}
                >
                  What can I help you buy today?
                </h1>
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex-1 overflow-y-auto pb-44 pt-4">
                  <div className="mx-auto w-full max-w-5xl space-y-3">
                    {chatMessages.map((message) => (
                      <div
                        key={message.id}
                        className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        {message.role === "user" ? (
                          <div className="max-w-[88%] rounded-2xl bg-white/10 px-5 py-3 text-lg text-white md:max-w-[70%]">
                            {message.content}
                          </div>
                        ) : (
                          <div
                            className={`max-w-[88%] whitespace-pre-wrap px-2 py-2 text-lg leading-relaxed md:max-w-[75%] ${
                              message.error ? "text-rose-200" : "text-white"
                            } ${message.pending ? "animate-pulse" : ""}`}
                          >
                            {message.content}
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>
                </div>
              </div>
            )}

            <div
              className={cn(
                "pointer-events-none fixed bottom-0 right-0 z-20 bg-gradient-to-t from-[#1f2025] via-[#1f2025] to-transparent px-3 pb-2 pt-5 md:px-6 lg:px-8",
                isDesktopViewport ? (desktopSidebarOpen ? "lg:left-72" : "lg:left-16") : "left-0"
              )}
            >
              <div className="pointer-events-auto mx-auto w-full max-w-5xl">
                <PromptArea
                  mode={hasConversation ? "chat" : "hero"}
                  isSubmitting={pendingPrompt}
                  onSubmit={handlePromptSubmit}
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
