"use client";

/**
 * / — Home Screen (Lovable redesign, ported 2026-07-18).
 *
 * The redesigned home is a project "journey map": each active project is an
 * expandable accordion showing its 5-phase lifecycle (Site → Estimate →
 * Contract → Project → Operate). Tapping a phase opens its journey detail.
 * Below the accordion sits a 2-col action-tile row (Requests / Approvals /
 * Metrics / Pipeline).
 *
 * Ported from quill-platform-builder src/routes/index.tsx. Wired to prod's
 * real api.ts hooks (envelope-adapted: useProjects/useProjectRequests return
 * {items,...}). Prod's AvatarMenu (profile / settings / sign-out sheet) is
 * preserved — the Lovable mock dropped it, but it is required functionality.
 *
 * Auth-gated via MobileShell (redirects to /login). FloatingHomeButton is
 * hidden on "/" by the shell.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Archive,
  BarChart3,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  LogOut,
  MessageSquare,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  Terminal,
  Truck,
  User,
  Users,
  X,
} from "lucide-react";
import { MobileShell } from "@/components/layout/MobileShell";
import {
  JOURNEY,
  phaseStatus,
  stepStatus,
  currentJourneyPhase,
  type JourneyPhaseKey,
} from "@/lib/journey";
import {
  useApprovals,
  useLogout,
  useProjects,
  useProjectRequests,
  useSites,
  useSession,
} from "@/lib/api";
import type { QuillProject, Session, Site } from "@/lib/schemas";
import { siteAddress, workloadLabel } from "@/components/sites/SiteCard";
import { isRejectedSite, isSiteInProgress } from "@/lib/sites";
import { cn } from "@/lib/utils";

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function HomePage() {
  return (
    <MobileShell>
      <HomeScreen />
    </MobileShell>
  );
}

function HomeScreen() {
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;
  const { data: projectsData } = useProjects();
  const { data: approvals } = useApprovals();
  const { data: requestsData } = useProjectRequests();
  const { data: sitesData } = useSites();

  const projects = React.useMemo<QuillProject[]>(
    () => projectsData?.items ?? [],
    [projectsData],
  );
  const active = React.useMemo(
    () => projects.filter((p) => p.status !== "cancelled"),
    [projects],
  );
  const [expandedId, setExpandedId] = React.useState<string | null>(null);

  // Sites still moving through evaluation (not yet decided/advanced to a
  // project, and not rejected/archived). Surfaced below the projects so a new
  // site is visible from home.
  const sitesInProgress = React.useMemo(
    () => (sitesData ?? []).filter(isSiteInProgress),
    [sitesData],
  );
  const archivedCount = React.useMemo(
    () => (sitesData ?? []).filter(isRejectedSite).length,
    [sitesData],
  );

  const pendingApprovals = React.useMemo(
    () => (approvals ?? []).filter((a) => a.status === "pending").length,
    [approvals],
  );
  const openRequests = React.useMemo(
    () => (requestsData?.items ?? []).filter((r) => r.status === "processing").length,
    [requestsData],
  );

  const [now, setNow] = React.useState<Date | null>(null);
  React.useEffect(() => setNow(new Date()), []);

  const firstName =
    session?.display_name?.split(" ")[0] || session?.email?.split("@")[0] || "there";

  const dateLabel = now
    ? now.toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        timeZone: "America/New_York",
      })
    : "";

  return (
    <div className="mx-auto w-full max-w-[708px] px-4 pt-safe md:max-w-4xl md:px-8 lg:px-10">
      {/* ── Greeting ── */}
      <header className="flex items-start justify-between pt-6 pb-4">
        <div className="min-w-0">
          <p className="text-footnote font-medium uppercase tracking-wide text-label-secondary/60">
            {dateLabel || "\u00A0"}
          </p>
          <h1 className="mt-0.5 text-large-title text-label-primary">
            {now ? greetingFor(now.getHours()) : "Hello"}, {firstName}
          </h1>
          <p className="mt-1 text-subhead text-label-secondary">
            Tap a project to see its phases.
          </p>
        </div>
        <AvatarMenu session={session} />
      </header>

      {/* ── Projects (accordion) ── */}
      {active.length > 0 ? (
        <ProjectsAccordion
          projects={active}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((cur) => (cur === id ? null : id))}
        />
      ) : (
        <div className="glass mt-6 rounded-2xl p-6 text-center">
          <p className="text-body text-label-primary">No active projects yet.</p>
          <p className="mt-1 text-footnote text-label-secondary">
            Start by adding a site — that’s the first step of the journey.
          </p>
          <Link
            href="/sites/new"
            className="no-tap-highlight ease-ios mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-callout font-semibold text-white active:scale-[0.98] duration-tap"
          >
            <Building2 className="h-4 w-4" aria-hidden />
            Start a New Site
          </Link>
        </div>
      )}

      {/* ── Sites in progress (below projects) ── */}
      {sitesInProgress.length > 0 && (
        <SitesInProgress sites={sitesInProgress} />
      )}

      {/* ── Archive entry (rejected sites) ── */}
      {archivedCount > 0 && (
        <Link
          href="/sites/archive"
          className="no-tap-highlight ease-ios mt-3 flex items-center gap-3 rounded-2xl bg-bg-elevated px-4 py-3 border border-hairline active:scale-[0.99] duration-tap"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-label-quaternary/15">
            <Archive className="h-4 w-4 text-label-secondary" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-callout font-semibold text-label-primary">Archive</span>
            <span className="block text-caption-1 text-label-tertiary">
              {archivedCount} rejected {archivedCount === 1 ? "site" : "sites"}
            </span>
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-label-tertiary" aria-hidden />
        </Link>
      )}

      {/* ── Primary CTA: start a new site (the entry point for site intake) ── */}
      <Link
        href="/sites/new"
        className="no-tap-highlight ease-ios mt-6 flex items-center gap-3 rounded-2xl bg-accent px-5 py-4 shadow-card active:scale-[0.99] duration-tap"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/20">
          <Building2 className="h-5 w-5 text-white" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-headline font-semibold text-white">Start a New Site</span>
          <span className="block text-footnote text-white/85">
            Add a site to kick off a project
          </span>
        </span>
        <ChevronRight className="h-5 w-5 shrink-0 text-white/80" aria-hidden />
      </Link>

      {/* ── Action tiles ── */}
      <section aria-label="Quick actions" className="mt-3 mb-8 grid grid-cols-2 gap-3">
        <ActionTile
          href="/requests"
          icon={<MessageSquare className="h-6 w-6" aria-hidden />}
          count={openRequests}
          label="Requests"
        />
        <ActionTile
          href="/queue"
          icon={<CheckCircle2 className="h-6 w-6" aria-hidden />}
          count={pendingApprovals}
          label="Approvals"
        />
        <ActionTile
          href="/metrics"
          icon={<BarChart3 className="h-6 w-6" aria-hidden />}
          label="Metrics"
        />
        <ActionTile
          href="/pipeline"
          icon={<Target className="h-6 w-6" aria-hidden />}
          label="Pipeline"
        />
      </section>
    </div>
  );
}

function ActionTile({
  href,
  icon,
  count,
  label,
}: {
  href: string;
  icon: React.ReactNode;
  count?: number;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="no-tap-highlight ease-ios flex flex-col items-start gap-2 rounded-2xl bg-bg-elevated p-4 shadow-card active:scale-[0.98] duration-tap"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-tint text-accent">
        {icon}
      </span>
      <span className="mt-1 flex items-baseline gap-1.5">
        {typeof count === "number" && (
          <span className="text-title-3 font-bold text-label-primary">{count}</span>
        )}
        <span className="text-footnote font-semibold text-label-secondary">{label}</span>
      </span>
    </Link>
  );
}

const SITE_STATUS_LABEL: Record<string, string> = {
  intake: "Intake",
  researching: "Researching",
  scoring: "Scoring",
  review: "Review",
  decided: "Decided",
};

function SitesInProgress({ sites }: { sites: Site[] }) {
  return (
    <section aria-label="Sites in progress" className="mt-6">
      <p className="text-caption-1 mb-1.5 ml-1 font-semibold uppercase tracking-wide text-label-tertiary">
        Sites in progress
      </p>
      <div className="space-y-2">
        {sites.map((s) => {
          const status = s.status ?? "intake";
          const score = s.scores?.total_weighted;
          return (
            <Link
              key={s.site_id}
              href={`/sites/${encodeURIComponent(s.site_id)}`}
              className="no-tap-highlight ease-ios flex items-center gap-3 rounded-2xl bg-bg-elevated px-4 py-3.5 shadow-card active:scale-[0.99] duration-tap"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-tint text-accent">
                <Building2 className="h-5 w-5" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-headline font-semibold text-label-primary">
                  {siteAddress(s)}
                </span>
                <span className="mt-0.5 block truncate text-footnote text-label-secondary">
                  {workloadLabel(s.target_workload)}
                  {s.target_mw ? ` · ${s.target_mw} MW` : ""}
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-caption-1 font-semibold text-label-secondary">
                  {SITE_STATUS_LABEL[status] ?? status}
                </span>
                {typeof score === "number" && (
                  <span className="text-caption-2 text-label-tertiary">{Math.round(score)}/100</span>
                )}
              </span>
              <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-label-quaternary" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function ProjectsAccordion({
  projects,
  expandedId,
  onToggle,
}: {
  projects: QuillProject[];
  expandedId: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <section aria-label="Active project" className="mt-3">
      <p className="text-caption-1 mb-1.5 ml-1 font-semibold uppercase tracking-wide text-label-tertiary">
        Projects
      </p>
      <div className="space-y-3">
        {projects.map((p) => (
          <ProjectAccordionItem
            key={p.id}
            project={p}
            expanded={p.id === expandedId}
            onToggle={() => onToggle(p.id)}
          />
        ))}
      </div>
    </section>
  );
}

function ProjectAccordionItem({
  project,
  expanded,
  onToggle,
}: {
  project: QuillProject;
  expanded: boolean;
  onToggle: () => void;
}) {
  const journeyPhase = currentJourneyPhase(project);
  const currentPhaseLabel = JOURNEY.find((j) => j.key === journeyPhase)?.label ?? "";
  const progress =
    project.milestone_total > 0
      ? `${project.milestone_complete} of ${project.milestone_total} milestones`
      : "No milestones yet";
  return (
    <div className="overflow-hidden rounded-2xl bg-bg-elevated shadow-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="no-tap-highlight ease-ios flex w-full items-center gap-3 px-4 py-4 text-left active:bg-bg-tertiary duration-tap"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-headline font-semibold text-label-primary">
            {project.name}
          </span>
          <span className="mt-0.5 block truncate text-footnote text-label-secondary">
            <span className="font-semibold text-accent">{currentPhaseLabel}</span>
            <span className="text-label-tertiary"> · {progress}</span>
          </span>
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            "h-5 w-5 shrink-0 text-label-tertiary transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t border-separator/60">
          {JOURNEY.map((phase) => (
            <PhaseSubRow
              key={phase.key}
              projectId={project.id}
              phaseKey={phase.key}
              label={phase.label}
              tagline={phase.tagline}
              project={project}
              isLast={false}
            />
          ))}
          <ProjectSupportingTiles projectId={project.id} />
        </div>
      )}
    </div>
  );
}

function ProjectSupportingTiles({ projectId }: { projectId: string }) {
  const items = [
    { href: "/documents", label: "Documents", Icon: FolderOpen },
    { href: "/compliance", label: "Compliance", Icon: ShieldCheck },
    { href: "/supply-chain", label: "Supply chain", Icon: Truck },
    { href: "/customers", label: "Customers", Icon: Users },
  ] as const;
  return (
    <div className="border-t border-separator/60 bg-bg/40 px-3 py-3">
      <p className="mb-2 ml-1 text-caption-1 font-semibold uppercase tracking-wide text-label-tertiary">
        For this project
      </p>
      <div className="grid grid-cols-4 gap-2">
        {items.map(({ href, label, Icon }) => (
          <Link
            key={href}
            href={`${href}?project=${encodeURIComponent(projectId)}`}
            className="no-tap-highlight ease-ios flex flex-col items-center gap-1.5 rounded-xl bg-bg-elevated px-2 py-3 shadow-card active:scale-[0.97] duration-tap"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-tint text-accent">
              <Icon className="h-4 w-4" />
            </span>
            <span className="text-caption-2 font-semibold text-label-secondary text-center leading-tight">
              {label}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function PhaseSubRow({
  projectId,
  phaseKey,
  label,
  tagline,
  project,
  isLast,
}: {
  projectId: string;
  phaseKey: JourneyPhaseKey;
  label: string;
  tagline: string;
  project: QuillProject;
  isLast: boolean;
}) {
  const status = phaseStatus(phaseKey, project);
  const phase = JOURNEY.find((j) => j.key === phaseKey)!;
  const complete = phase.steps.filter(
    (_, i) => stepStatus(phaseKey, i, project) === "complete",
  ).length;
  const meta =
    status === "complete"
      ? "Complete"
      : status === "current"
        ? `${complete}/${phase.steps.length} steps · In progress`
        : `${phase.steps.length} steps · Upcoming`;
  return (
    <Link
      href={`/journey/${encodeURIComponent(projectId)}/${phaseKey}`}
      className={cn(
        "no-tap-highlight ease-ios flex items-center gap-3 px-4 py-3 active:bg-bg-tertiary duration-tap",
        !isLast && "border-b border-separator/50",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-caption-1 font-bold",
          status === "complete"
            ? "bg-success text-white"
            : status === "current"
              ? "border-2 border-accent bg-bg text-accent"
              : "border border-hairline bg-bg text-label-tertiary",
        )}
      >
        {status === "complete" ? <Check className="h-4 w-4" strokeWidth={2.8} /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-callout",
            status === "current"
              ? "font-bold text-label-primary"
              : status === "complete"
                ? "font-semibold text-label-primary"
                : "font-semibold text-label-secondary",
          )}
        >
          {label}
        </span>
        <span className="mt-0.5 block truncate text-caption-1 text-label-tertiary">
          {meta} · {tagline}
        </span>
      </span>
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-label-quaternary" />
    </Link>
  );
}

/* ── Avatar + account sheet (preserved from prod home) ─────────────────── */
function AvatarMenu({ session }: { session: Session | null | undefined }) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const logout = useLogout();

  const initials = (session?.display_name || session?.email || "?")
    .split(" ")
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const items = [
    { label: "Profile", icon: User, onSelect: () => router.push("/profile") },
    { label: "Settings", icon: Settings, onSelect: () => router.push("/settings") },
    { label: "Assistant", icon: Sparkles, onSelect: () => router.push("/assistant") },
    { label: "Dev Chat", icon: Terminal, onSelect: () => router.push("/dev-chat") },
    {
      label: "Sign out",
      icon: LogOut,
      destructive: true,
      onSelect: () =>
        logout.mutate(undefined, { onSuccess: () => router.replace("/login") }),
    },
  ];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        className="mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-callout font-semibold text-white no-tap-highlight active:opacity-80 transition-state ease-ios"
      >
        {initials}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            role="menu"
            aria-label="Account"
            className="glass-strong fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl pb-safe animate-sheet-in"
          >
            <div className="flex items-center justify-between px-4 pt-3 pb-2">
              <div className="min-w-0">
                <p className="truncate text-headline text-label-primary">
                  {session?.display_name || "Account"}
                </p>
                {session?.email && (
                  <p className="truncate text-footnote text-label-secondary">{session.email}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-bg-elevated text-label-secondary active:opacity-70 no-tap-highlight"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <ul className="flex flex-col px-2 pb-3">
              {items.map(({ label, icon: Icon, onSelect, destructive }) => (
                <li key={label}>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setOpen(false);
                      onSelect();
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-4 py-3 min-h-[52px]",
                      "no-tap-highlight active:bg-bg-elevated",
                      destructive ? "text-danger" : "text-label-primary",
                    )}
                  >
                    <Icon className="h-5 w-5" strokeWidth={1.8} aria-hidden="true" />
                    <span className="text-body font-medium">{label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
