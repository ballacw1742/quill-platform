"use client";

/**
 * Portal Layout — Sprint 4B
 *
 * LIGHT THEME: white background, blue accents, clean sans-serif.
 * Not the dark Quill ops console — this is customer-facing.
 *
 * Auth check: if no portal_session_token in localStorage, redirect to /portal/login.
 */

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import { LogOut, Zap } from "lucide-react";
import { usePortalMe } from "@/lib/api";
import { setPortalToken } from "@/lib/api";

function PortalNav() {
  const router = useRouter();
  const { data: me } = usePortalMe();

  function handleLogout() {
    setPortalToken(null);
    router.replace("/portal/login");
  }

  return (
    <header className="portal-nav h-14 border-b border-gray-200 bg-white flex items-center px-6 gap-4 shadow-sm">
      {/* Logo / Brand */}
      <div className="flex items-center gap-2 text-blue-600 font-bold text-lg select-none">
        <Zap className="w-5 h-5 fill-blue-600 text-blue-600" />
        <span>Quill</span>
        <span className="text-gray-400 font-normal text-sm ml-1">Customer Portal</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* User info */}
      {me && (
        <span className="text-sm text-gray-600 hidden sm:block">
          {me.name}
        </span>
      )}

      {/* Logout */}
      <button
        type="button"
        onClick={handleLogout}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-red-500 transition-colors px-2 py-1 rounded-md hover:bg-red-50"
        aria-label="Sign out"
      >
        <LogOut className="w-4 h-4" />
        <span className="hidden sm:block">Sign out</span>
      </button>
    </header>
  );
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = React.useState(false);

  React.useEffect(() => {
    // Don't redirect from the login page
    if (pathname === "/portal/login") {
      setChecked(true);
      return;
    }
    const token =
      typeof window !== "undefined"
        ? window.localStorage.getItem("portal_session_token")
        : null;
    if (!token) {
      router.replace("/portal/login");
    } else {
      setChecked(true);
    }
  }, [pathname, router]);

  // On login page, render without the nav
  if (pathname === "/portal/login") {
    return (
      <div className="min-h-screen bg-gray-50 font-sans">
        {children}
      </div>
    );
  }

  if (!checked) return null;

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      <PortalNav />
      <main className="max-w-5xl mx-auto px-4 py-8">
        {children}
      </main>
    </div>
  );
}
