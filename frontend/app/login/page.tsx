"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  const handleSubmit = async () => {
    setLoading(true);
    setError("");

    if (isSignUp) {
      const { error } = await supabase.auth.signUp({ email, password });
      if (error) setError(error.message);
      else router.push("/");
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) setError(error.message);
      else router.push("/");
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-[#0b0f19] flex items-center justify-center">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 w-full max-w-md">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
            <span className="text-white text-lg">🚀</span>
          </div>
          <h1 className="text-xl font-bold text-white">Founder Buddy</h1>
        </div>

        <h2 className="text-2xl font-bold text-white mb-2">
          {isSignUp ? "Create account" : "Welcome back"}
        </h2>
        <p className="text-slate-400 text-sm mb-8">
          {isSignUp ? "Start building your business plan" : "Sign in to continue"}
        </p>

        <div className="space-y-4">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 transition-colors"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSubmit()}
            className="w-full bg-slate-800 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <button
          onClick={handleSubmit}
          disabled={loading || !email || !password}
          className="w-full mt-6 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium py-3 rounded-xl transition-colors"
        >
          {loading ? "..." : isSignUp ? "Create account" : "Sign in"}
        </button>

        <p className="text-center text-slate-400 text-sm mt-4">
          {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
          <button
            onClick={() => setIsSignUp(!isSignUp)}
            className="text-blue-400 hover:text-blue-300 transition-colors"
          >
            {isSignUp ? "Sign in" : "Sign up"}
          </button>
        </p>
      </div>
    </div>
  );
}