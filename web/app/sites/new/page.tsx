"use client";

/**
 * /sites/new — Submit a new site evaluation (Sprint DC.2)
 *
 * Uses the simplified CreateSiteRequest model (flat fields) via POST /api/v1/sites.
 * On success, redirects to /sites/[id].
 *
 * Design: dark Quill theme, iOS-style form cards.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Building2, Loader2, FolderOpen, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useCreateSite } from "@/lib/api";

// ── Field helpers ─────────────────────────────────────────────────────────────

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
      {children}
    </label>
  );
}

function FieldInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-xl px-4 py-3 text-body text-label-primary",
        "bg-bg-elevated border border-separator/60",
        "placeholder:text-label-quaternary",
        "focus:outline-none focus:border-accent",
        "transition-colors",
        props.className,
      )}
    />
  );
}

function FieldSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        "w-full rounded-xl px-4 py-3 text-body text-label-primary",
        "bg-bg-elevated border border-separator/60",
        "focus:outline-none focus:border-accent",
        "transition-colors appearance-none",
        props.className,
      )}
    />
  );
}

function FieldTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      rows={props.rows ?? 3}
      className={cn(
        "w-full rounded-xl px-4 py-3 text-body text-label-primary",
        "bg-bg-elevated border border-separator/60",
        "placeholder:text-label-quaternary",
        "focus:outline-none focus:border-accent",
        "transition-colors resize-none",
        props.className,
      )}
    />
  );
}

function FormCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl bg-chrome/80 border border-separator/40 p-5 mb-4", className)}>
      {children}
    </div>
  );
}

// ── Form state ────────────────────────────────────────────────────────────────

interface FormState {
  address: string;
  city: string;
  state: string;
  zip: string;
  latitude: string;
  longitude: string;
  acres: string;
  target_workload: string;
  target_mw: string;
  fiber_providers: string;
  zoning_status: string;
  flood_zone: string;
  notes: string;
  drive_folder_url: string;
}

const INITIAL_STATE: FormState = {
  address: "",
  city: "",
  state: "",
  zip: "",
  latitude: "",
  longitude: "",
  acres: "",
  target_workload: "ai_hpc",
  target_mw: "",
  fiber_providers: "",
  zoning_status: "",
  flood_zone: "no",
  notes: "",
  drive_folder_url: "",
};

const WORKLOAD_OPTIONS = [
  { value: "hyperscale_compute", label: "Hyperscale Compute" },
  { value: "ai_hpc", label: "AI / HPC" },
  { value: "edge_latency", label: "Edge / Latency" },
  { value: "colocation", label: "Colocation" },
  { value: "mixed", label: "Mixed" },
];

const US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
  "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY","DC",
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function NewSitePage() {
  const router = useRouter();
  const [form, setForm] = React.useState<FormState>(INITIAL_STATE);
  const [errors, setErrors] = React.useState<Partial<Record<keyof FormState, string>>>({});
  const [uploadFiles, setUploadFiles] = React.useState<File[]>([]);
  const [submitStep, setSubmitStep] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const createSite = useCreateSite({
    onSuccess: async (site) => {
      const siteId = site.site_id;
      // Step 2: Attach Drive folder if provided
      if (form.drive_folder_url.trim()) {
        setSubmitStep("Attaching Drive folder…");
        try {
          const token = typeof window !== "undefined" ? localStorage.getItem("quill_token") : null;
          await fetch(`/api/v1/sites/${encodeURIComponent(siteId)}/documents/drive`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ drive_folder_url: form.drive_folder_url.trim() }),
          });
        } catch {
          // Non-fatal — continue to file upload and redirect
        }
      }
      // Step 3: Upload supporting documents one at a time
      if (uploadFiles.length > 0) {
        setSubmitStep(`Uploading ${uploadFiles.length} document(s)…`);
        const token = typeof window !== "undefined" ? localStorage.getItem("quill_token") : null;
        for (const file of uploadFiles) {
          try {
            const fd = new FormData();
            fd.append("files", file);
            await fetch(`/api/v1/sites/${encodeURIComponent(siteId)}/documents`, {
              method: "POST",
              headers: {
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
              },
              body: fd,
            });
          } catch {
            // Non-fatal — document upload failure shouldn't block redirect
          }
        }
      }
      // Step 4: Redirect to site detail
      router.push(`/sites/${siteId}`);
    },
    onError: (err) => {
      setSubmitStep(null);
      setErrors({ address: err.message ?? "Submission failed." });
    },
  });

  function set(key: keyof FormState) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [key]: e.target.value }));
      setErrors((prev) => ({ ...prev, [key]: undefined }));
    };
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    setUploadFiles(files);
  }

  function removeFile(idx: number) {
    setUploadFiles((prev) => prev.filter((_, i) => i !== idx));
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function validate(): boolean {
    const e: Partial<Record<keyof FormState, string>> = {};

    // At-least-one rule: address OR (latitude AND longitude)
    const hasAddress = form.address.trim().length > 0;
    const latStr = form.latitude.trim();
    const lonStr = form.longitude.trim();
    const hasLat = latStr.length > 0;
    const hasLon = lonStr.length > 0;
    const hasCoords = hasLat && hasLon;

    if (!hasAddress && !hasCoords) {
      e.address = "Provide a street address or GPS coordinates (latitude + longitude)";
    }
    // Partial coords: one without the other
    if (hasLat && !hasLon) e.longitude = "Longitude is required when latitude is provided";
    if (hasLon && !hasLat) e.latitude = "Latitude is required when longitude is provided";

    // Range validation for coordinates
    if (hasLat) {
      const lat = parseFloat(latStr);
      if (isNaN(lat) || lat < -90 || lat > 90)
        e.latitude = "Latitude must be a number between -90 and 90";
    }
    if (hasLon) {
      const lon = parseFloat(lonStr);
      if (isNaN(lon) || lon < -180 || lon > 180)
        e.longitude = "Longitude must be a number between -180 and 180";
    }

    if (!form.target_workload) e.target_workload = "Workload type is required";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    setSubmitStep("Creating site record…");
    const payload: Record<string, any> = {
      target_workload: form.target_workload,
      lead_source: "internal",
    };
    // Include address fields only if provided
    if (form.address.trim()) payload.address = form.address.trim();
    if (form.city.trim()) payload.city = form.city.trim();
    if (form.state.trim()) payload.state = form.state.toUpperCase();
    if (form.zip.trim()) payload.zip = form.zip.trim();
    // Include coordinates if provided
    if (form.latitude.trim()) payload.latitude = parseFloat(form.latitude.trim());
    if (form.longitude.trim()) payload.longitude = parseFloat(form.longitude.trim());
    if (form.acres) payload.acres = parseFloat(form.acres);
    if (form.target_mw) payload.target_mw = parseFloat(form.target_mw);
    // Store extras in a notes-like field; DataSite's CreateSiteRequest is lean
    const noteParts: string[] = [];
    if (form.fiber_providers) noteParts.push(`Fiber providers: ${form.fiber_providers}`);
    if (form.zoning_status) noteParts.push(`Zoning: ${form.zoning_status}`);
    if (form.flood_zone === "yes") noteParts.push("Flood zone: yes");
    if (form.notes) noteParts.push(form.notes);
    if (noteParts.length > 0) payload.notes = noteParts.join(" | ");

    createSite.mutate(payload);
  }

  const isPending = createSite.isPending || submitStep !== null;

  return (
    <MobileShell>
      <TopBar
        title="New Site"
        left={
          <button
            type="button"
            onClick={() => router.back()}
            className="flex items-center gap-1 text-accent font-semibold text-callout"
          >
            <ArrowLeft className="h-4 w-4" />
            Sites
          </button>
        }
      />

      <form onSubmit={handleSubmit} className="px-4 pt-3 pb-12">
        {/* Location */}
        <FormCard>
          <p className="text-callout font-semibold text-label-primary mb-4">Location</p>

          <div className="mb-4">
            <FieldLabel>Street Address</FieldLabel>
            <FieldInput
              placeholder="3990 E Broad Street"
              value={form.address}
              onChange={set("address")}
              autoComplete="street-address"
            />
            {/* Address error shown in coords section below when combined with coords */}
            {errors.address && form.address.trim() && (
              <p className="text-caption-1 text-red-400 mt-1">{errors.address}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <FieldLabel>City</FieldLabel>
              <FieldInput
                placeholder="Columbus"
                value={form.city}
                onChange={set("city")}
              />
              {errors.city && <p className="text-caption-1 text-red-400 mt-1">{errors.city}</p>}
            </div>
            <div>
              <FieldLabel>State</FieldLabel>
              <FieldSelect value={form.state} onChange={set("state")}>
                <option value="">Select</option>
                {US_STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </FieldSelect>
              {errors.state && <p className="text-caption-1 text-red-400 mt-1">{errors.state}</p>}
            </div>
          </div>

          <div>
            <FieldLabel>ZIP Code</FieldLabel>
            <FieldInput
              placeholder="43213"
              value={form.zip}
              onChange={set("zip")}
              inputMode="numeric"
              maxLength={10}
            />
            {errors.zip && <p className="text-caption-1 text-red-400 mt-1">{errors.zip}</p>}
          </div>

          {/* Coordinate entry (alternative to address) */}
          <div className="mt-4 pt-4 border-t border-separator/30">
            <p className="text-caption-1 text-label-tertiary mb-3">
              <strong className="text-label-secondary">Or enter GPS coordinates</strong>
              {" "}— provide latitude + longitude instead of (or in addition to) an address.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel>Latitude</FieldLabel>
                <FieldInput
                  placeholder="39.9612"
                  type="number"
                  step="any"
                  min="-90"
                  max="90"
                  value={form.latitude}
                  onChange={set("latitude")}
                />
                {errors.latitude && (
                  <p className="text-caption-1 text-red-400 mt-1">{errors.latitude}</p>
                )}
              </div>
              <div>
                <FieldLabel>Longitude</FieldLabel>
                <FieldInput
                  placeholder="-82.9988"
                  type="number"
                  step="any"
                  min="-180"
                  max="180"
                  value={form.longitude}
                  onChange={set("longitude")}
                />
                {errors.longitude && (
                  <p className="text-caption-1 text-red-400 mt-1">{errors.longitude}</p>
                )}
              </div>
            </div>
            {errors.address && !form.address.trim() && (
              <p className="text-caption-1 text-red-400 mt-2">{errors.address}</p>
            )}
          </div>
        </FormCard>

        {/* Site Details */}
        <FormCard>
          <p className="text-callout font-semibold text-label-primary mb-4">Site Details</p>

          <div className="mb-4">
            <FieldLabel>Target Workload *</FieldLabel>
            <FieldSelect value={form.target_workload} onChange={set("target_workload")}>
              {WORKLOAD_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </FieldSelect>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <FieldLabel>Parcel Size (acres)</FieldLabel>
              <FieldInput
                placeholder="250"
                type="number"
                min="0"
                step="0.1"
                value={form.acres}
                onChange={set("acres")}
              />
            </div>
            <div>
              <FieldLabel>Available Power (MW)</FieldLabel>
              <FieldInput
                placeholder="100"
                type="number"
                min="0"
                step="1"
                value={form.target_mw}
                onChange={set("target_mw")}
              />
            </div>
          </div>

          <div className="mb-4">
            <FieldLabel>Fiber Providers Present</FieldLabel>
            <FieldInput
              placeholder="AT&T, Lumen, Zayo"
              value={form.fiber_providers}
              onChange={set("fiber_providers")}
            />
          </div>

          <div className="mb-4">
            <FieldLabel>Zoning Status</FieldLabel>
            <FieldInput
              placeholder="M-2 Industrial, pending rezoning"
              value={form.zoning_status}
              onChange={set("zoning_status")}
            />
          </div>

          <div>
            <FieldLabel>Flood Zone</FieldLabel>
            <FieldSelect value={form.flood_zone} onChange={set("flood_zone")}>
              <option value="no">No</option>
              <option value="yes">Yes</option>
              <option value="unknown">Unknown</option>
            </FieldSelect>
          </div>
        </FormCard>

        {/* Notes + Drive + Docs */}
        <FormCard>
          <p className="text-callout font-semibold text-label-primary mb-4">Additional Notes</p>

          <div className="mb-4">
            <FieldTextarea
              placeholder="Any other context about this site…"
              value={form.notes}
              onChange={set("notes")}
              rows={4}
            />
          </div>

          {/* Google Drive Folder */}
          <div className="mb-4">
            <FieldLabel>Google Drive Folder (optional)</FieldLabel>
            <div className="relative">
              <FolderOpen className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-label-tertiary pointer-events-none" />
              <FieldInput
                placeholder="https://drive.google.com/drive/folders/…"
                value={form.drive_folder_url}
                onChange={set("drive_folder_url")}
                className="pl-9"
                type="url"
                inputMode="url"
              />
            </div>
            <p className="text-caption-1 text-label-quaternary mt-1">
              Share a Drive folder containing site docs — the research agents will index it.
            </p>
          </div>

          {/* File Upload */}
          <div>
            <FieldLabel>Supporting Documents (optional)</FieldLabel>
            <label
              className={cn(
                "flex flex-col items-center justify-center gap-2 w-full",
                "rounded-xl border border-dashed border-separator/60 bg-bg-elevated",
                "px-4 py-5 cursor-pointer transition-colors",
                "hover:border-accent/50 hover:bg-accent/5",
              )}
            >
              <Paperclip className="h-5 w-5 text-label-tertiary" />
              <span className="text-caption-1 text-label-secondary text-center">
                {uploadFiles.length > 0
                  ? `${uploadFiles.length} file${uploadFiles.length > 1 ? "s" : ""} selected`
                  : "Tap to attach PDF or DOCX files"}
              </span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx"
                multiple
                className="sr-only"
                onChange={handleFileChange}
              />
            </label>
            <p className="text-caption-1 text-label-quaternary mt-1">
              Phase 1 ESA, geotech reports, utility LOIs, title docs, appraisals
            </p>
            {uploadFiles.length > 0 && (
              <ul className="mt-2 space-y-1">
                {uploadFiles.map((f, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 text-caption-1 text-label-secondary">
                    <span className="truncate">{f.name}</span>
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="text-label-tertiary hover:text-red-400 transition-colors shrink-0 text-caption-1"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </FormCard>

        {/* Submit */}
        <button
          type="submit"
          disabled={isPending}
          className={cn(
            "w-full py-3.5 rounded-2xl font-semibold text-body",
            "bg-accent text-white",
            "transition-all active:scale-[0.98]",
            "flex items-center justify-center gap-2",
            isPending && "opacity-60 cursor-not-allowed",
          )}
        >
          {isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {submitStep ?? "Submitting…"}
            </>
          ) : (
            <>
              <Building2 className="h-4 w-4" />
              Submit Site Evaluation
            </>
          )}
        </button>
      </form>
    </MobileShell>
  );
}
