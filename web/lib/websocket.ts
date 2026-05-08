"use client";

import { useEffect, useRef } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { USE_MOCK } from "@/lib/api";
import { mockStore } from "@/lib/mock/store";

type WsEvent =
  | { type: "approval.created"; approval_id: string }
  | { type: "approval.updated"; approval_id: string }
  | { type: "approval.executed"; approval_id: string }
  | { type: "audit.appended"; seq: number };

function applyEvent(qc: QueryClient, _e: WsEvent) {
  qc.invalidateQueries({ queryKey: ["approvals"] });
  qc.invalidateQueries({ queryKey: ["audit"] });
  qc.invalidateQueries({ queryKey: ["health"] });
}

export function useApprovalsSocket() {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (USE_MOCK) {
      // Mock: subscribe to mock-store mutations and re-fan to react-query.
      const unsub = mockStore.subscribe(() => applyEvent(qc, { type: "approval.updated", approval_id: "" }));
      return () => {
        unsub();
      };
    }

    const url =
      process.env.NEXT_PUBLIC_WS_URL ||
      (typeof window !== "undefined"
        ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/approvals`
        : "");
    if (!url) return;

    let cancelled = false;
    let backoff = 1000;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        backoff = 1000;
      };
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data) as WsEvent;
          applyEvent(qc, data);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 15_000);
      };
      ws.onerror = () => ws.close();
    };
    connect();

    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, [qc]);
}
