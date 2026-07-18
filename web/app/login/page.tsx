"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { QuillLogo } from "@/components/QuillLogo";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useLogin } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const login = useLogin();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [error, setError] = React.useState("");
  // Guards against the effect firing a redirect more than once (which was part
  // of the old flicker loop).
  const redirectedRef = React.useRef(false);

  const loading = login.isPending;

  // If already authenticated (token present AND the session query confirms it),
  // go home. We prime the session query rather than trusting localStorage
  // alone, so we never bounce to "/" before the shell's session gate agrees.
  React.useEffect(() => {
    if (redirectedRef.current) return;
    if (typeof window === "undefined") return;
    const token = window.localStorage.getItem("quill_session_token");
    if (!token) return;
    redirectedRef.current = true;
    // Make the shell's useSession see the token immediately (no stale null).
    qc.invalidateQueries({ queryKey: ["session"] });
    router.replace("/");
  }, [router, qc]);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password || loading) return;
    setError("");

    try {
      // useLogin stores the JWT AND invalidates the ["session"] query on
      // success — so the shell's auth gate re-reads a FRESH session instead of
      // the stale `null` cached from the /login visit. That stale-cache race
      // was the cause of the post-login flicker + error + manual-refresh.
      await login.mutateAsync({ email: email.trim(), password });
      // Ensure the session query is settled before navigating home.
      await qc.invalidateQueries({ queryKey: ["session"] });
      redirectedRef.current = true;
      router.replace("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      // Normalize the common credential failure to something friendly.
      setError(/40[13]/.test(msg) ? "Incorrect email or password." : msg);
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
