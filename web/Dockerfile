FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Build the app with production settings baked in
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_OUTPUT_STANDALONE=1
# Client-side: use same-origin (Next.js rewrites proxy to backend)
ENV NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_USE_MOCK=0
ENV NEXT_PUBLIC_DEV_AUTH_FALLBACK=1
# Server-side API URL — Next.js rewrites() run at build time, so this must be set here
# The web app proxies /api/v1/* -> backend at build time
ENV INTERNAL_API_URL=https://quill-agents-qdur2ylusq-uc.a.run.app
# Ensure public dir exists (Next.js requires it)
RUN mkdir -p public
# TypeScript errors and ESLint are skipped in Docker build (handled in CI)
# via next.config.mjs typescript.ignoreBuildErrors and eslint.ignoreDuringBuilds
RUN npm run build

# Production runner
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

# public dir may be empty — copy only if it exists (always exists after mkdir in builder)
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
