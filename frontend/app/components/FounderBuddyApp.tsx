"use client";

import { Rocket, Settings } from "lucide-react";
import ProgressTracker, { type ProgressState } from "./ProgressTracker";
import ConversationList from "./ConversationList";
import ChatInterface, { type Message } from "./ChatInterface";
import BusinessPlanDisplay from "./BusinessPlanDisplay";
import { createClient } from "@/lib/supabase";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";

const API_BASE_URL = "https://founder-buddy-backend.fly.dev";

const initialProgress: ProgressState = {
  problem: "pending",
  product: "pending",
  features: "pending",
  team_traction: "pending",
  investment: "pending",
  exit_strategy: "pending",
};

export default function FounderBuddyApp() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [progress, setProgress] = useState<ProgressState>(initialProgress);
  const [businessPlan, setBusinessPlan] = useState<string | null>(null);
  const [streamingBP, setStreamingBP] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [convListKey, setConvListKey] = useState(0);
  const [user, setUser] = useState<User | null>(null);
  const supabase = createClient();
  const router = useRouter();

  useEffect(() => {
    const checkUser = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      setUser(user);
      if (!user) router.push("/login");
    };
    checkUser();
  }, []);

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/login");
  };

  const handleSendMessage = async (content: string) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content,
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${session?.access_token}`,
      };

      // First message: use /chat/start (JSON, no streaming needed)
      if (!sessionId) {
        const response = await fetch(`${API_BASE_URL}/chat/start`, {
          method: "POST",
          headers,
          body: JSON.stringify({ message: content }),
        });
        const data = await response.json();
        setSessionId(data.session_id);
        setConvListKey(k => k + 1);
        if (data.section_status && Object.keys(data.section_status).length > 0) {
          setProgress(data.section_status);
        }
        if (data.agent_message) {
          setMessages((prev) => [...prev, {
            id: (Date.now() + 1).toString(),
            role: "assistant",
            content: data.agent_message,
          }]);
        }
        return;
      }

      // Subsequent messages: use /chat/stream (SSE)
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify({ session_id: sessionId, message: content }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Server error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const processBuffer = () => {
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "token") {
              setStreamingBP((prev) => prev + event.content);
            } else if (event.type === "done") {
              // Set businessPlan before clearing streamingBP to avoid a
              // render frame where both are empty and the panel unmounts
              if (event.is_done && event.business_plan) {
                setBusinessPlan(event.business_plan);
              }
              setStreamingBP("");
              if (event.section_status && Object.keys(event.section_status).length > 0) {
                setProgress(event.section_status);
              }
              if (event.agent_message) {
                setMessages((prev) => [...prev, {
                  id: (Date.now() + 1).toString(),
                  role: "assistant",
                  content: event.agent_message,
                }]);
              }
            } else if (event.type === "error") {
              throw new Error(event.detail ?? "Stream error");
            }
          } catch (e) {
            if (e instanceof SyntaxError) continue; // malformed SSE — skip
            throw e;
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // Flush any bytes still held in the decoder's internal buffer
          // (e.g. a multi-byte UTF-8 sequence split across the last chunk)
          buffer += decoder.decode();
          processBuffer();
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        processBuffer();
      }
    } catch (error) {
      console.error("Error:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: "Sorry, there was an error. Please try again.",
        },
      ]);
    } finally {
      // Always clear streaming state even if the stream ends without a done event
      setStreamingBP("");
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (businessPlan) {
      setConvListKey(k => k + 1);
    }
  }, [businessPlan]);

  const handleNewConversation = () => {
    setSessionId(null);
    setMessages([]);
    setProgress(initialProgress);
    setBusinessPlan(null);
    setStreamingBP("");
    setIsLoading(false); // reset in case a fetch was in-flight when the user switched
  };

  const handleLoadConversation = async (sessionId: string, businessPlan: string | null) => {
    setSessionId(sessionId);
    setBusinessPlan(businessPlan);
    setIsLoading(false);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers = { "Authorization": `Bearer ${session?.access_token}` };

      let loadedMessages: Message[] = [];
      const msgResponse = await fetch(
        `${API_BASE_URL}/chat/messages?session_id=${encodeURIComponent(sessionId)}`,
        { headers }
      );
      if (msgResponse.ok) {
        const msgData = await msgResponse.json();
        loadedMessages = msgData.messages.map(
          (m: { role: string; content: string; id: number }) => ({
            id: m.id.toString(),
            role: m.role as "user" | "assistant",
            content: m.content,
          })
        );
        setMessages(loadedMessages);
      }

      const stateResponse = await fetch(
        `${API_BASE_URL}/chat/state?session_id=${encodeURIComponent(sessionId)}`,
        { headers }
      );
      if (stateResponse.ok) {
        const data = await stateResponse.json();
        if (data.section_status) setProgress(data.section_status);
        if (data.business_plan) setBusinessPlan(data.business_plan);

        // Show the pending question if it isn't already the last DB message.
        // This covers the race where _persist_stream hasn't flushed yet, and
        // also makes it obvious what the agent is waiting for on resume.
        if (data.agent_message) {
          const last = loadedMessages[loadedMessages.length - 1];
          const alreadyShown =
            last?.role === "assistant" && last.content === data.agent_message;
          if (!alreadyShown) {
            setMessages((prev) => [
              ...prev,
              {
                id: `pending-${Date.now()}`,
                role: "assistant" as const,
                content: data.agent_message,
              },
            ]);
          }
        }
      } else if (stateResponse.status === 404) {
        // Session exists in the database but has no graph checkpoint — it was
        // likely created before the PostgreSQL checkpointer was configured.
        // Sending messages would fail with a confusing 404, so clear the
        // session and let the user know they need to start fresh.
        setSessionId(null);
        setMessages((prev) => [
          ...prev,
          {
            id: `notice-${Date.now()}`,
            role: "assistant" as const,
            content:
              "This conversation can't be resumed (it's from an older session). " +
              "You can still view the history above, but please start a new conversation to continue.",
          },
        ]);
      }
    } catch (error) {
      console.error("Error loading conversation:", error);
    }
  };

  return (
    <div className="h-full flex flex-col bg-[#f8fafc] overflow-hidden font-sans">
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-[30%] min-w-[300px] max-w-[400px] bg-[#0b0f19] border-r border-slate-800/60 p-6 flex flex-col relative overflow-hidden">
          <div className="absolute top-[-10%] left-[-10%] w-[120%] h-64 bg-blue-600/10 blur-[100px] pointer-events-none" />

          <div className="mb-8 relative z-10">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/25">
                <Rocket className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight">Founder Buddy</h1>
            </div>
            <p className="text-sm text-slate-400">Validate and refine your startup idea</p>
          </div>

          <div className="flex-1 overflow-y-auto pr-2 relative z-10 flex flex-col gap-8">
            <ProgressTracker status={progress} />
            <ConversationList
              onNewConversation={handleNewConversation}
              onLoadConversation={handleLoadConversation}
              refreshKey={convListKey}
            />
          </div>

          <div className="mt-4 pt-4 border-t border-slate-800/60 relative z-10">
            <div className="flex items-center gap-3 p-2 rounded-xl hover:bg-slate-800/40 transition-colors cursor-pointer group">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 border-2 border-slate-700/50 flex items-center justify-center text-sm font-bold text-white uppercase">
                {user?.email?.[0] ?? "U"}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-slate-200 truncate">{user?.email}</div>
                <div className="text-xs text-blue-400/90 font-medium">Pro Plan</div>
              </div>
              <button
                type="button"
                onClick={handleSignOut}
                aria-label="Sign out"
                className="text-slate-500 group-hover:text-slate-300 transition-colors"
              >
                <Settings className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>

        {/* Main */}
        <div className="flex-1 p-4 md:p-8 overflow-y-auto bg-gradient-to-b from-blue-50/50 to-[#f8fafc]">
          <div className="max-w-4xl mx-auto w-full h-full flex flex-col">
            <ChatInterface
              messages={messages}
              onSendMessage={handleSendMessage}
              isLoading={isLoading}
            />
            {(streamingBP || businessPlan) && (
              <div className="mt-8">
                <BusinessPlanDisplay
                  content={streamingBP || businessPlan!}
                  streaming={!!streamingBP}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
