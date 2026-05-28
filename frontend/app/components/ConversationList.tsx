"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase";
import { Trash2 } from "lucide-react";

interface Props {
  onNewConversation: () => void;
  onLoadConversation: (sessionId: string, businessPlan: string | null) => void;
  refreshKey?: number;
}

interface Conversation {
  id: number;
  user_id: string;
  session_id: string;
  created_at: string;
  business_plans?: { content: string }[];
  messages?: { content: string; role: string }[];
}

function getConversationLabel(conversation: Conversation) {
  const content = conversation.business_plans?.[0]?.content;
  if (content) {
    return content.length > 40 ? `${content.slice(0, 40)}...` : content;
  }
  const firstUserMessage = conversation.messages?.find((m) => m.role === "user");
  if (firstUserMessage) {
    const text = firstUserMessage.content;
    return text.length > 40 ? `${text.slice(0, 40)}...` : text;
  }
  return "New conversation";
}

function formatDate(date: string) {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export default function ConversationList({ onNewConversation, onLoadConversation, refreshKey }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const handleDelete = async (
    e: React.MouseEvent | React.KeyboardEvent,
    conversationId: number
  ) => {
    e.stopPropagation();
    const supabase = createClient();
    await supabase.from("conversations").delete().eq("id", conversationId);
    setConversations((prev) => prev.filter((c) => c.id !== conversationId));
  };

  useEffect(() => {
    const fetchConversations = async () => {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();

      if (!user) {
        setIsLoading(false);
        return;
      }

      const { data } = await supabase
        .from("conversations")
        .select("*, business_plans(content), messages(content, role)")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(10);

      setConversations((data as Conversation[]) ?? []);
      setIsLoading(false);
    };

    fetchConversations();
  }, [refreshKey]);

  return (
    <div className="space-y-4 mt-6 pt-6 border-t border-slate-800/60">
      <button
        onClick={onNewConversation}
        className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 py-2.5 px-4 rounded-xl border border-slate-700 hover:border-slate-600 transition-all group"
      >
        <svg className="w-4 h-4 text-slate-400 group-hover:text-blue-400 transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        <span className="font-medium text-sm">New Blueprint</span>
      </button>

      <div className="space-y-3">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Recent Plans</h3>
        {isLoading ? (
          <div className="text-sm text-slate-500 text-center py-6 bg-slate-800/20 rounded-xl border border-slate-800/50 border-dashed">
            Loading conversations...
          </div>
        ) : conversations.length === 0 ? (
          <div className="text-sm text-slate-500 text-center py-6 bg-slate-800/20 rounded-xl border border-slate-800/50 border-dashed">
            No past conversations
          </div>
        ) : (
          <div className="space-y-2">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                onClick={() =>
                  onLoadConversation(
                    conversation.session_id,
                    conversation.business_plans?.[0]?.content ?? null
                  )
                }
                className="group w-full text-left p-3 pr-10 rounded-xl bg-slate-800/40 hover:bg-slate-800 border border-slate-800/60 hover:border-slate-700 transition-all relative"
              >
                <div className="text-sm font-medium text-slate-300 truncate">
                  {getConversationLabel(conversation)}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {formatDate(conversation.created_at)}
                </div>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label="Delete conversation"
                  onClick={(e) => handleDelete(e, conversation.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      handleDelete(e, conversation.id);
                    }
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-all p-1.5 rounded-lg hover:bg-red-500/10"
                >
                  <Trash2 className="w-4 h-4" />
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
