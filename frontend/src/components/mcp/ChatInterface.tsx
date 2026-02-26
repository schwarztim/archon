import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { ChatMessage } from "@/api/mcp";
import { submitAction } from "@/api/mcp";
import { MessageBubble } from "./MessageBubble";

// ── Types ────────────────────────────────────────────────────────────

interface ChatInterfaceProps {
  /** Current session ID for action routing */
  sessionId: string | null;
  /** Messages to display */
  messages: ChatMessage[];
  /** Called when the user sends a new text message */
  onSendMessage: (text: string) => void;
  /** Whether the agent is currently processing */
  loading?: boolean;
}

// ── Component ────────────────────────────────────────────────────────

/**
 * Full chat interface with message list, input bar, and action handling.
 * User messages appear on the right; agent responses with embedded
 * MCP components appear on the left.
 */
export function ChatInterface({
  sessionId,
  messages,
  onSendMessage,
  loading = false,
}: ChatInterfaceProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    onSendMessage(text);
  }, [input, onSendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  async function handleAction(
    action: string,
    payload: Record<string, unknown>,
  ) {
    if (!sessionId) return;
    try {
      await submitAction(sessionId, action, payload);
    } catch {
      // Errors are surfaced by the global error handler
    }
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-surface-border bg-surface-raised">
      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
      >
        {messages.length === 0 && (
          <p className="py-12 text-center text-sm text-gray-500">
            Start a conversation with the agent…
          </p>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onAction={handleAction}
          />
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Loader2 size={14} className="animate-spin" />
            Agent is thinking…
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-surface-border p-3">
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-surface-border bg-surface-base px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
            placeholder="Ask the agent something…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <Button
            size="sm"
            onClick={handleSend}
            disabled={!input.trim() || loading}
          >
            <Send size={14} className="mr-1.5" />
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
