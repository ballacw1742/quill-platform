"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { QuillLogo } from "@/components/QuillLogo";
import { Eye, EyeOff, Loader2 } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (typeof window !== "undefined") {
      setError("");
      const token = window.localStorage.getItem("quill_session_token");
      if (token) router.replace("/");
    }
  }, [router]);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });

      let data: { detail?: string; access_token?: string };
      try {
        data = await res.json();
      } catch {
        throw new Error(`Server error (${res.status})`);
      }

      if (!res.ok) throw new Error(data?.detail || `Login failed (${res.status})`);

      if (data.access_token) {
        window.localStorage.setItem("quill_session_token", data.access_token);
        router.replace("/");
      } else {
        throw new Error("No session token in response");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center gap-3">
          <QuillLogo size={80} />
          <span className="text-2xl font-semibold text-label-primary">Quill</span>
          <p className="text-sm text-label-secondary text-center">Agentic PMO Platform</p>
        </div>

        <form onSubmit={handleSignIn} className="flex flex-col gap-3">
          {error && (
            <p className="text-sm text-red-500 text-center px-2">{error}</p>
          )}

          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            className="w-full h-[52px] rounded-xl px-4 text-[15px] bg-bg-elevated border border-separator/60 text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent transition-colors"
          />

          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full h-[52px] rounded-xl px-4 pr-12 text-[15px] bg-bg-elevated border border-separator/60 text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-label-tertiary"
              tabIndex={-1}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>

          <button
            type="submit"
            disabled={loading || !email.trim() || !password}
            className="w-full h-[52px] rounded-xl bg-accent text-white font-semibold text-[15px] flex items-center justify-center gap-2 transition disabled:opacity-50 active:scale-[0.98]"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Signing in…
              </>
            ) : (
              "Sign In"
            )}
          </button>
        </form>
      </div>
    </main>
  );
}
