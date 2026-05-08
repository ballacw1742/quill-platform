import { NextRequest, NextResponse } from "next/server";

// Optional: forward /api/proxy/<path> to the upstream FastAPI. Useful when CORS
// is locked down or you want a same-origin URL during dev. The default
// next.config.mjs rewrites cover most cases; this exists as a server-side
// escape hatch for header transforms or auth-bound proxies.

const UPSTREAM = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function forward(req: NextRequest, params: { path: string[] }) {
  const target = `${UPSTREAM}/${params.path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: stripHopByHop(req.headers),
    body:
      req.method === "GET" || req.method === "HEAD"
        ? undefined
        : await req.arrayBuffer().then((b) => (b.byteLength ? b : undefined)),
    cache: "no-store",
    redirect: "manual",
  };
  const upstream = await fetch(target, init);
  const headers = new Headers(upstream.headers);
  headers.delete("transfer-encoding");
  headers.delete("content-encoding");
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

function stripHopByHop(h: Headers) {
  const out = new Headers(h);
  ["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade", "host"].forEach((k) =>
    out.delete(k),
  );
  return out;
}

export const GET = (req: NextRequest, ctx: { params: { path: string[] } }) => forward(req, ctx.params);
export const POST = (req: NextRequest, ctx: { params: { path: string[] } }) => forward(req, ctx.params);
export const PUT = (req: NextRequest, ctx: { params: { path: string[] } }) => forward(req, ctx.params);
export const PATCH = (req: NextRequest, ctx: { params: { path: string[] } }) => forward(req, ctx.params);
export const DELETE = (req: NextRequest, ctx: { params: { path: string[] } }) => forward(req, ctx.params);
export const dynamic = "force-dynamic";
