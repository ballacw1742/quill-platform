import type { Config } from "tailwindcss";

/**
 * Quill iOS-redesign Tailwind config.
 *
 * Authoritative contract: web/DESIGN_SYSTEM.md §2 (color), §3 (typography),
 * §4 (spacing), §5 (radii / elevation), §6 (motion), §8 (icons).
 *
 * All colors are sourced from CSS custom properties in app/globals.css so
 * `dark:` mode is the same `class="dark"` toggle but the values are the iOS
 * system color palette, not Tailwind's default zinc/slate.
 *
 * Legacy semantic names (background, foreground, primary, success, etc.)
 * are retained as aliases so existing components keep working without a
 * mass rename; they map to the iOS tokens (e.g. primary = accent).
 */
const config: Config = {
  darkMode: ["class", "media"], // honour both .dark class and prefers-color-scheme
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      // ── Apple system font stack (DESIGN_SYSTEM §3) ─────────────────────
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Text"',
          '"SF Pro Display"',
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          '"SF Mono"',
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      // ── iOS Dynamic Type scale (DESIGN_SYSTEM §3) ──────────────────────
      // Format: [size, { lineHeight, fontWeight }]
      // Use these tokens; never raw text-sm / text-xs / text-2xl in UI code.
      fontSize: {
        "large-title": ["34px", { lineHeight: "41px", fontWeight: "700", letterSpacing: "0.011em" }],
        "title-1":     ["28px", { lineHeight: "34px", fontWeight: "700", letterSpacing: "0.012em" }],
        "title-2":     ["22px", { lineHeight: "28px", fontWeight: "700", letterSpacing: "0.014em" }],
        "title-3":     ["20px", { lineHeight: "25px", fontWeight: "600", letterSpacing: "0.015em" }],
        headline:      ["17px", { lineHeight: "22px", fontWeight: "600", letterSpacing: "-0.022em" }],
        body:          ["17px", { lineHeight: "22px", fontWeight: "400", letterSpacing: "-0.022em" }],
        callout:       ["16px", { lineHeight: "21px", fontWeight: "400", letterSpacing: "-0.021em" }],
        subhead:       ["15px", { lineHeight: "20px", fontWeight: "400", letterSpacing: "-0.016em" }],
        footnote:      ["13px", { lineHeight: "18px", fontWeight: "400", letterSpacing: "-0.008em" }],
        "caption-1":   ["12px", { lineHeight: "16px", fontWeight: "400", letterSpacing: "0" }],
        "caption-2":   ["11px", { lineHeight: "13px", fontWeight: "400", letterSpacing: "0.006em" }],
      },
      // ── Color tokens (DESIGN_SYSTEM §2) ────────────────────────────────
      colors: {
        // iOS-native semantics
        bg: "rgb(var(--bg) / <alpha-value>)",
        "bg-elevated": "rgb(var(--bg-elevated) / <alpha-value>)",
        "bg-tertiary": "rgb(var(--bg-tertiary) / <alpha-value>)",
        separator: "rgb(var(--separator) / <alpha-value>)",
        "separator-opaque": "rgb(var(--separator-opaque) / <alpha-value>)",
        label: {
          DEFAULT: "rgb(var(--label-primary) / <alpha-value>)",
          primary: "rgb(var(--label-primary) / <alpha-value>)",
          secondary: "rgb(var(--label-secondary) / <alpha-value>)",
          tertiary: "rgb(var(--label-tertiary) / <alpha-value>)",
          quaternary: "rgb(var(--label-quaternary) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          pressed: "rgb(var(--accent-pressed) / <alpha-value>)",
          tint: "rgb(var(--accent-tint) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        // System statuses (DESIGN_SYSTEM §2)
        success: {
          DEFAULT: "rgb(var(--success) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        warning: {
          DEFAULT: "rgb(var(--warning) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        danger: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        info: {
          DEFAULT: "rgb(var(--info) / <alpha-value>)",
          foreground: "#FFFFFF",
        },

        // ── Legacy semantic aliases (for unmodified components) ─────────
        background: "rgb(var(--bg) / <alpha-value>)",
        foreground: "rgb(var(--label-primary) / <alpha-value>)",
        border: "rgb(var(--separator-opaque) / <alpha-value>)",
        input: "rgb(var(--separator-opaque) / <alpha-value>)",
        ring: "rgb(var(--accent) / <alpha-value>)",
        primary: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        secondary: {
          DEFAULT: "rgb(var(--bg-elevated) / <alpha-value>)",
          foreground: "rgb(var(--label-primary) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "rgb(var(--bg-elevated) / <alpha-value>)",
          foreground: "rgb(var(--label-secondary) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",
          foreground: "#FFFFFF",
        },
        popover: {
          DEFAULT: "rgb(var(--bg-tertiary) / <alpha-value>)",
          foreground: "rgb(var(--label-primary) / <alpha-value>)",
        },
        card: {
          DEFAULT: "rgb(var(--bg-tertiary) / <alpha-value>)",
          foreground: "rgb(var(--label-primary) / <alpha-value>)",
        },
        lane: {
          tier0: "rgb(var(--danger) / <alpha-value>)",
          tier1: "rgb(var(--accent) / <alpha-value>)",
          tier2: "rgb(var(--label-tertiary) / <alpha-value>)",
        },
      },
      // ── Spacing (DESIGN_SYSTEM §4) ─────────────────────────────────────
      spacing: {
        // 4-px rhythm; standard Tailwind keys remain (1=4px etc.) so we
        // don't break existing components. Add iOS-named aliases.
        "screen-x": "16px",
        "tab-bar": "49px",
      },
      // ── Radii (DESIGN_SYSTEM §5) ───────────────────────────────────────
      borderRadius: {
        sm: "8px",
        md: "10px",
        lg: "12px",
        xl: "16px",
        "2xl": "22px",
      },
      // ── Shadows (DESIGN_SYSTEM §5) ─────────────────────────────────────
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.04), 0 0 1px rgba(0,0,0,0.06)",
        "card-dark": "0 0 0 1px rgba(255,255,255,0.05)",
        elevated: "0 4px 16px rgba(0,0,0,0.08)",
        "tab-bar": "0 -1px 0 0 rgb(var(--separator) / 1)",
      },
      // ── Motion (DESIGN_SYSTEM §6) ──────────────────────────────────────
      transitionTimingFunction: {
        ios: "cubic-bezier(0.32, 0.72, 0, 1)",
      },
      transitionDuration: {
        tap: "100ms",
        state: "200ms",
        sheet: "320ms",
        "sheet-out": "280ms",
        page: "240ms",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(2px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "sheet-in": {
          from: { transform: "translateY(100%)" },
          to: { transform: "translateY(0%)" },
        },
        "sheet-out": {
          from: { transform: "translateY(0%)" },
          to: { transform: "translateY(100%)" },
        },
        shimmer: {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "0.7" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.18s cubic-bezier(0.32,0.72,0,1)",
        "sheet-in": "sheet-in 320ms cubic-bezier(0.32,0.72,0,1)",
        "sheet-out": "sheet-out 280ms cubic-bezier(0.32,0.72,0,1)",
        shimmer: "shimmer 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [
    // Safe-area utilities for iOS notch / home indicator (DESIGN_SYSTEM §11).
    function safeAreaPlugin({ addUtilities }: { addUtilities: (utils: Record<string, Record<string, string>>) => void }) {
      addUtilities({
        ".pt-safe": { paddingTop: "env(safe-area-inset-top)" },
        ".pb-safe": { paddingBottom: "env(safe-area-inset-bottom)" },
        ".pl-safe": { paddingLeft: "env(safe-area-inset-left)" },
        ".pr-safe": { paddingRight: "env(safe-area-inset-right)" },
        ".min-h-tab-bar": { minHeight: "calc(49px + env(safe-area-inset-bottom))" },
        // Legacy tab-bar inset — the tab bar is gone (iOS home-screen model);
        // pb-tab-bar now reserves space for the floating Home button instead
        // so any stragglers stay un-overlapped.
        ".pb-tab-bar": {
          paddingBottom: "calc(88px + env(safe-area-inset-bottom))",
        },
        // Floating Home button inset: 56px button + 16px bottom margin +
        // 16px breathing room above it (UI_REDESIGN_BRIEF §4 no-overlap).
        ".pb-home": {
          paddingBottom: "calc(88px + env(safe-area-inset-bottom))",
        },
      });
    },
  ],
};
export default config;
