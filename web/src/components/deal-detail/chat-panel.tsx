"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, User, Send, Loader2, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

const QUICK_PROMPTS = [
  "What are the biggest risks in this deal?",
  "Summarize the return structure in plain English.",
  "How does leverage affect the downside case?",
  "What's missing from the offering memo?",
];

/**
 * Chat with Claude about this specific deal. The backend injects metrics +
 * scores + document text into the system prompt, so questions can be
 * specific ("what's the break-even occupancy?") and the model will know.
 *
 * Not streaming today — we POST once and render the whole response when it
 * comes back. UI fakes a short typing animation so the arrival feels smoother.
 */
export function ChatPanel({ dealId }: { dealId: number }) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [sending, setSending] = React.useState(false);
  const [input, setInput] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Load history on mount
  React.useEffect(() => {
    api
      .get<ChatMessage[]>(`/api/chat/history/${dealId}`)
      .then(setMessages)
      .catch(() => setMessages([]))
      .finally(() => setLoading(false));
  }, [dealId]);

  // Auto-scroll to bottom when messages change
  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function send(text: string) {
    const clean = text.trim();
    if (!clean || sending) return;
    setInput("");

    // Optimistic user message
    const temp: ChatMessage = {
      id: -Date.now(),
      role: "user",
      content: clean,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, temp]);
    setSending(true);

    try {
      const res = await api.post<{ response: string }>("/api/chat", {
        deal_id: dealId,
        message: clean,
      });
      const reply: ChatMessage = {
        id: Date.now(),
        role: "assistant",
        content: res.response,
        created_at: new Date().toISOString(),
      };
      setMessages((m) => [...m, reply]);
    } catch (err) {
      const detail = (err as { detail?: string })?.detail ?? "Chat failed";
      toast.error("Couldn't send message", { description: detail });
    } finally {
      setSending(false);
    }
  }

  async function clearHistory() {
    if (!confirm("Clear the chat history for this deal?")) return;
    try {
      await api.delete(`/api/chat/history/${dealId}`);
      setMessages([]);
      toast.success("History cleared");
    } catch {
      toast.error("Couldn't clear history");
    }
  }

  return (
    <Card elevated className="flex flex-col h-[calc(100vh-240px)] min-h-[520px] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-border/70">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-primary to-chart-3 grid place-items-center">
            <Sparkles className="h-3.5 w-3.5 text-primary-foreground" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">Deal Analyst</div>
            <div className="text-[10px] text-muted-foreground">
              Claude, grounded on this deal&apos;s metrics and uploaded docs.
            </div>
          </div>
        </div>
        {messages.length > 0 && (
          <Button size="sm" variant="ghost" onClick={clearHistory}>
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </Button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5 space-y-4">
        {loading ? (
          <div className="text-center text-xs text-muted-foreground py-8">Loading history…</div>
        ) : messages.length === 0 ? (
          <EmptyChat onPick={(q) => send(q)} />
        ) : (
          messages.map((m) => <MessageBubble key={m.id} msg={m} />)
        )}

        <AnimatePresence>
          {sending && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-start gap-3"
            >
              <Avatar role="assistant" />
              <div className="rounded-2xl rounded-tl-md bg-muted/60 px-4 py-3 inline-flex items-center gap-2">
                <TypingDots />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="border-t border-border/70 p-3"
      >
        <div className="relative">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={2}
            placeholder="Ask about IRR, leverage, sponsor quality, red flags…"
            className="w-full resize-none rounded-lg border border-border/70 bg-background/60 px-3.5 pr-12 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors"
          />
          <button
            type="submit"
            disabled={!input.trim() || sending}
            className={cn(
              "absolute right-2 bottom-2 h-8 w-8 rounded-md grid place-items-center transition-colors",
              input.trim() && !sending
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed",
            )}
            aria-label="Send"
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          </button>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">
          Enter to send · Shift+Enter for newline
        </div>
      </form>
    </Card>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex items-start gap-3", isUser && "flex-row-reverse")}
    >
      <Avatar role={msg.role} />
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-md"
            : "bg-muted/60 text-foreground rounded-tl-md",
        )}
      >
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </motion.div>
  );
}

function Avatar({ role }: { role: "user" | "assistant" }) {
  return (
    <div
      className={cn(
        "h-7 w-7 rounded-full grid place-items-center shrink-0 mt-0.5",
        role === "user" ? "bg-primary/15 text-primary" : "bg-gradient-to-br from-primary/30 to-chart-3/30 text-foreground",
      )}
    >
      {role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground"
          animate={{ opacity: [0.2, 1, 0.2] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </div>
  );
}

function EmptyChat({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="py-6 text-center">
      <div className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/30 mb-3">
        <Sparkles className="h-5 w-5 text-primary" />
      </div>
      <div className="text-sm font-medium">Ask anything about this deal</div>
      <div className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
        Claude has the extracted metrics and document text. Get a second-pair-of-eyes read in seconds.
      </div>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-md mx-auto">
        {QUICK_PROMPTS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="text-left text-xs px-3 py-2.5 rounded-lg border border-border/70 hover:bg-muted/40 hover:border-border transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
