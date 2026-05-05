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
  const [isLoading, setIsLoading] = useState(false);
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
      let data;
      const { data: { session } } = await supabase.auth.getSession();
      const headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${session?.access_token}`,
      };

      if (!sessionId) {
        const response = await fetch(`${API_BASE_URL}/chat/start`, {
          method: "POST",
          headers,
          body: JSON.stringify({ message: content }),
        });
        data = await response.json();
        setSessionId(data.session_id);
      } else {
        const response = await fetch(`${API_BASE_URL}/chat/message`, {
          method: "POST",
          headers,
          body: JSON.stringify({ session_id: sessionId, message: content }),
        });
        data = await response.json();
      }

      if (data.section_status && Object.keys(data.section_status).length > 0) {
        setProgress(data.section_status);
      }

      if (data.is_done && data.business_plan) {
        setBusinessPlan(data.business_plan);
      }

      if (data.agent_message) {
        const assistantMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: data.agent_message,
        };
        setMessages((prev) => [...prev, assistantMessage]);
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
      setIsLoading(false);
    }
  };

  const handleNewConversation = () => {
    setSessionId(null);
    setMessages([]);
    setProgress(initialProgress);
    setBusinessPlan(null);
  };

  const handleLoadConversation = async (sessionId: string, businessPlan: string | null) => {
    setSessionId(sessionId);
    setMessages([]);
    setProgress(initialProgress);
    setBusinessPlan(businessPlan);
    setIsLoading(false);

    try {
      const response = await fetch(`${API_BASE_URL}/chat/state?session_id=${encodeURIComponent(sessionId)}`);
      if (!response.ok) return;

      const data = await response.json();
      if (data.section_status && Object.keys(data.section_status).length > 0) {
        setProgress(data.section_status);
      }
      if (data.business_plan) {
        setBusinessPlan(data.business_plan);
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
            {businessPlan && (
              <div className="mt-8">
                <BusinessPlanDisplay content={businessPlan} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
