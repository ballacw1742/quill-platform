"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { QuillLogo } from "@/components/QuillLogo";
import { initializeApp, getApps } from "firebase/app";
import { getAuth, GoogleAuthProvider, signInWithPopup } from "firebase/auth";

const FIREBASE_CONFIG = {
  apiKey: "AIzaSyB_OqDH-Z139IrO79J0PHsHU-fW2xLIHhM",
  authDomain: "studio-1771635593-6661e.firebaseapp.com",
  projectId: "studio-1771635593-6661e",
};

function getFirebaseAuth() {
  const app = getApps().length === 0
    ? initializeApp(FIREBASE_CONFIG)
    : getApps()[0];
  return getAuth(app);
}

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (typeof window !== "undefined") {
      // Clear any stale error state
      setError("");
      const token = window.localStorage.getItem("quill_session_token");
      if (token) router.replace("/queue");
    }
  }, [router]);

  const handleGoogleSignIn = async () => {
    setLoading(true);
    setError("");
    try {
      const auth = getFirebaseAuth();
      const provider = new GoogleAuthProvider();
      const result = await signInWithPopup(auth, provider);
      
      let idToken: string;
      try {
        idToken = await result.user.getIdToken(true);
      } catch (tokenErr) {
        throw new Error("Failed to get auth token: " + String(tokenErr));
      }
      
      if (!idToken) throw new Error("No token received from Google");

      const res = await fetch("/api/v1/auth/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: idToken }),
      });

      let data: { detail?: string; access_token?: string };
      try {
        data = await res.json();
      } catch {
        throw new Error(`Server error (${res.status})`);
      }
      
      if (!res.ok) throw new Error(data?.detail || `Auth failed (${res.status})`);

      if (data.access_token) {
        window.localStorage.setItem("quill_session_token", data.access_token);
        router.replace("/queue");
      } else {
        throw new Error("No session token in response");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (!msg.includes("popup-closed") && !msg.includes("cancelled") && !msg.includes("auth/popup-closed")) {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm">
        <div className="mb-12 flex flex-col items-center gap-3">
          <QuillLogo size={80} />
          <span className="text-2xl font-semibold text-label-primary">Quill</span>
          <p className="text-sm text-label-secondary text-center">Agentic PMO Platform</p>
        </div>

        {error && (
          <p className="text-sm text-red-500 mb-4 text-center">{error}</p>
        )}

        <button
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full flex items-center justify-center gap-3 h-[52px] rounded-xl bg-white text-slate-900 font-medium text-[15px] border border-slate-200 shadow-sm hover:bg-slate-50 active:bg-slate-100 transition disabled:opacity-50"
        >
          {loading ? (
            <span className="text-slate-500">Signing in...</span>
          ) : (
            <>
              <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              Continue with Google
            </>
          )}
        </button>
      </div>
    </main>
  );
}
