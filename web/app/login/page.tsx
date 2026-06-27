"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { QuillLogo } from "@/components/QuillLogo";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  // If already logged in, go to queue
  React.useEffect(() => {
    const token = window.localStorage.getItem("quill_session_token");
    if (token) router.replace("/queue");
  }, [router]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || "Invalid email or password");
      }
      if (data.access_token) {
        // Store with the key the app actually reads
        window.localStorage.setItem("quill_session_token", data.access_token);
        router.replace("/queue");
      } else {
        throw new Error("No token returned");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center gap-3">
          <QuillLogo size={80} />
          <span className="text-2xl font-semibold text-label-primary">Quill</span>
        </div>
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm text-label-secondary mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
              className="w-full h-[50px] rounded-lg border border-separator-opaque bg-bg-tertiary px-3 text-body text-label-primary focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          <div>
            <label className="block text-sm text-label-secondary mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
              required
              className="w-full h-[50px] rounded-lg border border-separator-opaque bg-bg-tertiary px-3 text-body text-label-primary focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full h-[50px] rounded-lg bg-accent text-white font-medium text-body disabled:opacity-60 active:opacity-80 transition-opacity"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
