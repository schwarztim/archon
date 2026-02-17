import { Bot, User } from "lucide-react";
import { cn } from "@/utils/cn";
import type { ChatMessage } from "@/api/mcp";
import { ComponentRenderer } from "./ComponentRenderer";
import { ComponentSandbox } from "./ComponentSandbox";

// ── Types ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: ChatMessage;
  onAction?: (action: string, payload: Record<string, unknown>) => void;
}

// ── Component ────────────────────────────────────────────────────────

/**
 * Chat message bubble with optional embedded MCP components.
 * User messages align right; assistant messages align left.
 */
export function MessageBubble({ message, onAction }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}
    >
      {/* Avatar — assistant */}
      {!isUser && (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-purple-500/20">
          <Bot size={14} className="text-purple-400" />
        </div>
      )}

      {/* Bubble */}
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-3 py-2 text-sm",
          isUser
            ? "bg-purple-600/20 text-purple-200"
            : "bg-[#0f1117] text-gray-300",
        )}
      >
        {/* Text content */}
        {message.content && <p className="whitespace-pre-wrap">{message.content}</p>}

        {/* Embedded MCP components */}
        {message.components && message.components.length > 0 && (
          <div className="mt-3 space-y-3">
            {message.components.map((comp, i) => (
              <ComponentSandbox key={i} fallback>
                <ComponentRenderer component={comp} onAction={onAction} />
              </ComponentSandbox>
            ))}
          </div>
        )}
      </div>

      {/* Avatar — user */}
      {isUser && (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-500/20">
          <User size={14} className="text-gray-400" />
        </div>
      )}
    </div>
  );
}
