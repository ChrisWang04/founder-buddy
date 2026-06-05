"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Lightbulb } from "lucide-react";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface ChatInterfaceProps {
  messages: Message[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
  streamingMessage?: string;
  autoScroll?: boolean;
}

const examplePrompts = [
  { text: "I want to open a specialty coffee shop", icon: "☕" },
  { text: "I'm building a B2B SaaS for HR", icon: "🏢" },
  { text: "I have an idea for an AI fitness app", icon: "🤖" },
];

export default function ChatInterface({ messages, onSendMessage, isLoading, streamingMessage = "", autoScroll = true }: ChatInterfaceProps) {
  const [input, setInput] = useState("");
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!autoScroll) return;
    messagesContainerRef.current?.scrollTo({
      top: messagesContainerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, isLoading, streamingMessage, autoScroll]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input.trim());
      setInput("");
    }
  };

  return (
    <div className="flex flex-col h-full min-h-[600px] bg-white/70 backdrop-blur-xl rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] ring-1 ring-slate-200/50 overflow-hidden relative">
      {/* Top gradient bar */}
      <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-blue-400 via-indigo-500 to-purple-500" />

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-2xl px-4">
              <div className="flex justify-center mb-8">
                <div className="w-20 h-20 bg-gradient-to-b from-blue-50 to-white border border-blue-100/50 rounded-2xl shadow-xl flex items-center justify-center rotate-3">
                  <Lightbulb className="w-10 h-10 text-blue-600" />
                </div>
              </div>
              <h3 className="text-3xl font-bold mb-3 text-slate-800 tracking-tight">
                Welcome to Founder Buddy
              </h3>
              <p className="text-slate-500 mb-10 text-lg">
                Let&apos;s turn your concept into a comprehensive business plan.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {examplePrompts.map((prompt, index) => (
                  <button
                    key={index}
                    onClick={() => setInput(prompt.text)}
                    className="flex flex-col items-start gap-2 border border-slate-200/60 bg-white/50 rounded-2xl p-4 hover:border-blue-400/50 hover:bg-blue-50/30 hover:shadow-md hover:-translate-y-1 transition-all cursor-pointer text-left"
                  >
                    <span className="text-2xl">{prompt.icon}</span>
                    <span className="text-sm font-medium text-slate-700 leading-snug">{prompt.text}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {message.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center mr-3 flex-shrink-0 mt-1">
                <Lightbulb className="w-4 h-4 text-white" />
              </div>
            )}
            <div
              className={`max-w-[75%] px-5 py-4 ${
                message.role === "user"
                  ? "bg-gradient-to-br from-blue-600 to-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-md"
                  : "bg-white border border-slate-100 text-slate-800 rounded-2xl rounded-tl-sm shadow-sm"
              }`}
            >
              {message.role === "assistant" && (
                <div className="text-xs text-blue-600 mb-1.5 font-bold uppercase tracking-wider">
                  Founder Buddy
                </div>
              )}
              <div className="text-[15px] leading-relaxed whitespace-pre-wrap">{message.content}</div>
            </div>
          </div>
        ))}

        {streamingMessage && (
          <div className="flex justify-start">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center mr-3 flex-shrink-0 mt-1">
              <Lightbulb className="w-4 h-4 text-white" />
            </div>
            <div className="max-w-[75%] bg-white border border-slate-100 text-slate-800 rounded-2xl rounded-tl-sm shadow-sm px-5 py-4">
              <div className="text-xs text-blue-600 mb-1.5 font-bold uppercase tracking-wider">
                Founder Buddy
              </div>
              <div className="text-[15px] leading-relaxed whitespace-pre-wrap">
                {streamingMessage}
                <span className="inline-block w-0.5 h-4 bg-blue-500 ml-0.5 animate-pulse align-middle" />
              </div>
            </div>
          </div>
        )}

        {isLoading && !streamingMessage && (
          <div className="flex justify-start items-end">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center mr-3 flex-shrink-0">
              <Lightbulb className="w-4 h-4 text-white" />
            </div>
            <div className="bg-white border border-slate-100 rounded-2xl rounded-tl-sm shadow-sm px-5 py-4">
              <div className="flex gap-1.5 items-center h-4">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-2 h-2 bg-blue-500/60 rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.2}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} className="h-4" />
      </div>

      {/* Input */}
      <div className="p-4 md:p-6 bg-white/80 backdrop-blur-md border-t border-slate-100">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
          <div className="flex items-center bg-slate-50 border border-slate-200 focus-within:border-blue-400 focus-within:ring-4 focus-within:ring-blue-100 transition-all rounded-full p-1.5">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Describe your startup idea..."
              className="flex-1 bg-transparent outline-none text-[15px] px-4 py-2 text-slate-700 placeholder:text-slate-400"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white w-10 h-10 rounded-full flex items-center justify-center transition-all disabled:cursor-not-allowed shadow-md"
            >
              <Send className="w-4 h-4 ml-0.5" />
            </button>
          </div>
          <p className="text-center mt-2 text-xs text-slate-400 font-medium">
            Founder Buddy AI can make mistakes. Consider verifying details.
          </p>
        </form>
      </div>
    </div>
  );
}
