"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function BusinessPlanDisplay({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-white rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] ring-1 ring-slate-200/50 p-8 md:p-10 relative overflow-hidden">
      <div className="absolute top-0 right-0 w-64 h-64 bg-blue-50/50 rounded-full blur-3xl -z-10" />
      <div className="absolute bottom-0 left-0 w-64 h-64 bg-indigo-50/50 rounded-full blur-3xl -z-10" />

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-8 gap-4 border-b border-slate-100 pb-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Your Business Plan</h2>
          <p className="text-sm text-slate-500 mt-1">
            {streaming ? "Generating your plan…" : "Generated based on our conversation"}
          </p>
        </div>
        <button
          onClick={handleCopy}
          disabled={streaming}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-full transition-all text-sm font-medium ${
            copied
              ? "bg-emerald-50 text-emerald-600 border border-emerald-200"
              : streaming
              ? "bg-slate-50 text-slate-400 border border-slate-200 cursor-not-allowed"
              : "bg-white text-slate-700 border border-slate-200 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 shadow-sm"
          }`}
        >
          {copied ? (
            <><Check className="w-4 h-4" /><span>Copied!</span></>
          ) : (
            <><Copy className="w-4 h-4" /><span>Export Plan</span></>
          )}
        </button>
      </div>

      <div className="prose prose-slate max-w-none
        prose-h1:text-3xl prose-h1:font-extrabold prose-h1:text-slate-900
        prose-h2:text-2xl prose-h2:font-bold prose-h2:text-slate-800
        prose-h3:text-xl prose-h3:font-semibold prose-h3:text-slate-800
        prose-p:text-slate-600 prose-p:leading-relaxed
        prose-li:text-slate-600
        prose-strong:text-slate-800 prose-strong:font-semibold
        prose-table:w-full prose-table:border-collapse
        prose-th:bg-slate-50 prose-th:px-4 prose-th:py-2 prose-th:text-left prose-th:text-sm prose-th:font-semibold prose-th:text-slate-700 prose-th:border prose-th:border-slate-200
        prose-td:px-4 prose-td:py-2 prose-td:text-sm prose-td:text-slate-600 prose-td:border prose-td:border-slate-200
        prose-blockquote:border-l-4 prose-blockquote:border-blue-200 prose-blockquote:bg-blue-50/50 prose-blockquote:rounded-r-lg
        prose-hr:border-slate-100">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        {streaming && (
          <span className="inline-block w-0.5 h-5 bg-blue-500 ml-0.5 align-middle animate-pulse" />
        )}
      </div>
    </div>
  );
}