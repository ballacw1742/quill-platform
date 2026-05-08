# Quill — Web (Approval Queue)

The Approval Queue front-end for the Agentic PMO fleet. Sprint 1.2.

## Run

```bash
npm install
cp .env.example .env.local   # mock mode by default
npm run dev                  # http://localhost:3000
```

The default mode (`NEXT_PUBLIC_USE_MOCK=1`) runs entirely in-process with seeded
fixtures so the full happy path (login → queue → approve → audit) works without
the API. To talk to the real FastAPI backend instead:

```env
NEXT_PUBLIC_USE_MOCK=0
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/approvals
```

`next.config.mjs` sets up `/api/v1/*` and `/ws/*` rewrites to `NEXT_PUBLIC_API_URL`
to keep the browser on the same origin in dev.

## Pages

| Path | Purpose |
|------|---------|
| `/login` | Email/password (Sprint 1 stub). Passkey button is wired to a placeholder for Sprint 2. |
| `/queue` | Three lanes (Tier 0 / 1 / 2). Desktop side-by-side, mobile tabs. Search + filters + WebSocket live updates. |
| `/approvals/[id]` | Three-pane detail: proposed action, context/citations, decision panel (Approve / Edit / Reject / Escalate). Audit accordion. |
| `/audit` | Hash-chained audit log with filters and "Verify chain" action. |
| `/agents` | Fleet admin: trust tiers, budgets, error rates, approval-no-edit rates. |
| `/health` | Queue depth, errors, routing health, spend, audit chain status. |

## Tech

- Next.js 14 (App Router), TypeScript strict, Tailwind, Radix primitives
- TanStack Query for data, Zod for runtime validation, react-hook-form for forms
- Mock backend in `lib/mock/` (zero external deps); flip `NEXT_PUBLIC_USE_MOCK=0` for the real API
- Sonner for toasts, lucide-react for icons, date-fns for relative time
- All UI primitives in `components/ui/` are hand-built (shadcn-style; no `shadcn add`)

## Sprint 2 hooks

- `lib/auth.ts` exposes `challengePasskey()` / `isPasskeySupported()` placeholders.
- `components/approval/PasskeyChallengeModal.tsx` is the user-visible step. Swap the stub for `navigator.credentials.get(...)` when the backend ships challenge endpoints.
