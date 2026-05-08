import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function truncate(s: string, n = 100) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function formatPercent(n: number, digits = 0) {
  return `${(n * 100).toFixed(digits)}%`;
}

export function formatCurrency(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

export function shortHash(s: string, len = 8) {
  if (!s) return "";
  return s.length > len ? s.slice(0, len) : s;
}
