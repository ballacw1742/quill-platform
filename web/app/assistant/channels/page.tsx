"use client";

/**
 * /assistant/channels — Channel pairing (Phase D, agent-cloud/CHANNELS.md §13).
 *
 * A thin form over the JWT-gated api bridge (/v1/agent-cloud/channels/*):
 *   - pick a platform (Telegram | Google Chat) + one of the tenant's agents
 *   - generate a single-use pairing code → shown with copy + instructions
 *   - list existing links (platform, agent, status badge) → revoke
 *
 * tenant_id never appears here — the bridge injects it from the JWT
 * (workspace=personal|org). This page keeps the heavy lift in the backend.
 */

import * as React from "react";
import { toast } from "sonner";
import { ArrowLeft, Copy, Link2, Plus, Trash2 } from "lucide-react";

import { BackButton, MobileShell, TopBar } from "@/components/layout/MobileShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AgentCloudError,
  CHANNEL_PLATFORMS,
  CHANNEL_PLATFORM_LABELS,
  pairChannel,
  revokeChannel,
  useAgentCloudAgents,
  useAgentCloudChannels,
  useInvalidateChannels,
  type ChannelPairResult,
  type ChannelPlatform,
} from "@/lib/agent-cloud";

const AGENT_LABELS: Record<string, string> = {
  personal: "Personal",
  quill: "Quill",
};

function statusVariant(status: string): "success" | "warning" | "muted" {
  if (status === "linked") return "success";
  if (status === "pending") return "warning";
  return "muted"; // revoked
}

export function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function ChannelsPage() {
  const [platform, setPlatform] = React.useState<ChannelPlatform>("telegram");
  const [agentId, setAgentId] = React.useState<string>("personal");
  const [pairing, setPairing] = React.useState(false);
  const [result, setResult] = React.useState<ChannelPairResult | null>(null);
  const [revoking, setRevoking] = React.useState<string | null>(null);

  const agents = useAgentCloudAgents();
  const channels = useAgentCloudChannels();
  const invalidateChannels = useInvalidateChannels();

  const agentOptions = React.useMemo(() => {
    const list = agents.data?.items?.filter((a) => a.enabled) ?? [];
    if (list.length === 0) return [{ value: "personal", label: "Personal" }];
    return list.map((a) => ({
      value: a.agent_id,
      label: AGENT_LABELS[a.agent_id] ?? a.agent_id,
    }));
  }, [agents.data]);

  // Keep the picked agent valid as the list resolves.
  React.useEffect(() => {
    if (
      agentOptions.length > 0 &&
      !agentOptions.some((o) => o.value === agentId)
    ) {
      setAgentId(agentOptions[0].value);
    }
  }, [agentOptions, agentId]);

  async function handlePair() {
    if (pairing) return;
    setPairing(true);
    setResult(null);
    try {
      const out = await pairChannel({ agent_id: agentId, platform });
      setResult(out);
      invalidateChannels();
    } catch (e) {
      const msg =
        e instanceof AgentCloudError ? e.message : "Couldn't generate a code.";
      toast.error(msg);
    } finally {
      setPairing(false);
    }
  }

  async function handleRevoke(linkId: string) {
    if (revoking) return;
    setRevoking(linkId);
    try {
      await revokeChannel(linkId);
      toast.success("Channel revoked.");
      invalidateChannels();
      if (result?.link_id === linkId) setResult(null);
    } catch (e) {
      const msg =
        e instanceof AgentCloudError ? e.message : "Couldn't revoke the link.";
      toast.error(msg);
    } finally {
      setRevoking(null);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      toast.success("Code copied.");
    } catch {
      toast.error("Copy failed — select the code manually.");
    }
  }

  const links = channels.data?.items ?? [];

  return (
    <MobileShell>
      <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col">
        <TopBar
          title="Channels"
          left={<BackButton href="/assistant" label="Assistant" />}
        />

        <div className="flex flex-1 flex-col gap-6 px-4 py-4 pb-24">
          {/* ── Generate a pairing code ─────────────────────────────── */}
          <section className="flex flex-col gap-3 rounded-xl border border-separator bg-bg-elevated p-4">
            <div className="flex items-center gap-2">
              <Link2 className="h-5 w-5 text-accent" aria-hidden="true" />
              <h2 className="text-headline text-label-primary">
                Link a channel
              </h2>
            </div>
            <p className="text-footnote text-label-secondary">
              Generate a one-time code, then send it to the bot to link a chat
              to one of your agents.
            </p>

            <div className="flex flex-col gap-1">
              <Label>Platform</Label>
              <SegmentedControl
                ariaLabel="Platform"
                value={platform}
                onChange={(next) => setPlatform(next as ChannelPlatform)}
                options={CHANNEL_PLATFORMS.map((p) => ({
                  value: p,
                  label: CHANNEL_PLATFORM_LABELS[p],
                }))}
              />
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="channel-agent">Agent</Label>
              <Select value={agentId} onValueChange={setAgentId}>
                <SelectTrigger id="channel-agent" aria-label="Agent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {agentOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button
              type="button"
              onClick={handlePair}
              disabled={pairing || agentOptions.length === 0}
            >
              <Plus className="mr-1 h-4 w-4" />
              {pairing ? "Generating…" : "Generate pairing code"}
            </Button>

            {result && (
              <div
                className="mt-1 flex flex-col gap-2 rounded-lg border border-accent/40 bg-accent/5 p-3"
                data-testid="pairing-result"
              >
                <div className="flex items-center justify-between gap-2">
                  <code className="select-all font-mono text-title-3 tracking-wider text-label-primary">
                    {result.pairing_code}
                  </code>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label="Copy code"
                    onClick={() => copyCode(result.pairing_code)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="whitespace-pre-line text-footnote text-label-secondary">
                  {result.instructions}
                </p>
                {result.expires_at && (
                  <p className="text-caption-1 text-label-tertiary">
                    Expires {fmtTime(result.expires_at)}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* ── Existing links ──────────────────────────────────────── */}
          <section className="flex flex-col gap-2">
            <h2 className="px-1 text-footnote font-medium uppercase tracking-wide text-label-secondary">
              Linked channels
            </h2>

            {channels.isError && (
              <p className="px-1 text-footnote text-destructive">
                Couldn&apos;t load your channels. Pull to retry.
              </p>
            )}

            {channels.isLoading && (
              <p className="px-1 text-footnote text-label-secondary">Loading…</p>
            )}

            {!channels.isLoading && links.length === 0 && (
              <p className="px-1 py-4 text-center text-footnote text-label-secondary">
                No channels linked yet.
              </p>
            )}

            <ul className="flex flex-col gap-2">
              {links.map((link) => (
                <li
                  key={link.link_id}
                  data-testid="channel-row"
                  className="flex items-center justify-between gap-3 rounded-lg border border-separator bg-bg-elevated p-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-body text-label-primary">
                        {CHANNEL_PLATFORM_LABELS[
                          link.platform as ChannelPlatform
                        ] ?? link.platform}
                        {" · "}
                        {AGENT_LABELS[link.agent_id] ?? link.agent_id}
                      </span>
                      <Badge variant={statusVariant(link.status)}>
                        {link.status}
                      </Badge>
                    </div>
                    <p className="mt-0.5 truncate text-caption-1 text-label-secondary">
                      {link.display_name ? `${link.display_name} · ` : ""}
                      {link.status === "linked"
                        ? `linked ${fmtTime(link.linked_at)}`
                        : `created ${fmtTime(link.created_at)}`}
                    </p>
                  </div>
                  {link.status !== "revoked" && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      aria-label={`Revoke ${link.platform} link`}
                      disabled={revoking === link.link_id}
                      onClick={() => handleRevoke(link.link_id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </MobileShell>
  );
}
