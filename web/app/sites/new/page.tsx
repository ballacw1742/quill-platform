"use client";

/**
 * /sites/new — Submit a new site evaluation
 *
 * Visual layer ported from quill-platform-builder/src/routes/sites.new.tsx.
 * Data wired to prod useCreateSite() from @/lib/api.
 *
 * Key differences from Lovable version:
 * - Prod's form includes GPS coordinates (latitude/longitude) which Lovable omits
 * - Prod validates "address OR coords" while Lovable requires address fields
 * - Drive folder attachment and document upload are real POST calls, not mocked
 * - Error display matches Lovable's danger token pattern
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Building2, FolderOpen, Loader2, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useCreateSite } from "@/lib/api";

// ── Field helpers ─────────────────────────────────────────────────────────────

function inputCls(extra?: string) {
  return cn(
    "text-body w-full rounded-xl px-4 py-3 text-label-primary",
    "border border-hairline bg-bg-elevated",
    "placeholder:text-label-quaternary",
    "transition-colors focus:border-accent focus:outline-none",
    extra,
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-footnote mb-1.5 block font-semibold uppercase tracking-wide text-label-secondary">
      {children}
    </label>
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
  { value: "ai_hpc",            label: "AI / HPC" },
  { value: "edge_latency",      label: "Edge / Latency" },
  { value: "colocation",        label: "Colocation" },
  { value: "mixed",             label: "Mixed" },
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
      // Attach Drive folder if provided
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
      // Upload supporting documents one at a time
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
            // Non-fatal
          }
        }
      }
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
    setUploadFiles(Array.from(e.target.files ?? []));
  }

  function removeFile(idx: number) {
    setUploadFiles((prev) => prev.filter((_, i) => i !== idx));
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function validate(): boolean {
    const e: Partial<Record<keyof FormState, string>> = {};
    const hasAddress = form.address.trim().length > 0;
    const latStr = form.latitude.trim();
    const lonStr = form.longitude.trim();
    const hasLat = latStr.length > 0;
    const hasLon = lonStr.length > 0;
    const hasCoords = hasLat && hasLon;

    if (!hasAddress && !hasCoords) {
      e.address = "Provide a street address or GPS coordinates (latitude + longitude)";
    }
    if (hasLat && !hasLon) e.longitude = "Longitude is required when latitude is provided";
    if (hasLon && !hasLat) e.latitude = "Latitude is required when longitude is provided";

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
    const payload: Record<string, unknown> = {
      target_workload: form.target_workload,
      lead_source: "internal",
    };
    if (form.address.trim()) payload.address = form.address.trim();
    if (form.city.trim()) payload.city = form.city.trim();
    if (form.state.trim()) payload.state = form.state.toUpperCase();
    if (form.zip.trim()) payload.zip = form.zip.trim();
    if (form.latitude.trim()) payload.latitude = parseFloat(form.latitude.trim());
    if (form.longitude.trim()) payload.longitude = parseFloat(form.longitude.trim());
    if (form.acres) payload.acres = parseFloat(form.acres);
    if (form.target_mw) payload.target_mw = parseFloat(form.target_mw);
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
        right={
          <button
            type="button"
            onClick={() => router.back()}
            className="text-callout flex items-center gap-1 font-semibold text-accent"
          >
            <ArrowLeft className="h-4 w-4" /> Sites
          </button>
        }
      />

      <form
        onSubmit={handleSubmit}
        className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-12 md:max-w-4xl md:px-8"
      >
        {/* Location */}
        <div className="glass mb-4 rounded-2xl border border-hairline p-5">
          <p className="text-callout mb-4 font-semibold text-label-primary">Location</p>

          <div className="mb-4">
            <Label>Street Address</Label>
            <input
              className={inputCls()}
              placeholder="3990 E Broad Street"
              value={form.address}
              onChange={set("address")}
              autoComplete="street-address"
            />
            {errors.address && form.address.trim() && (
              <p className="text-caption-1 mt-1 text-danger">{errors.address}</p>
            )}
          </div>

          <div className="mb-4 grid grid-cols-2 gap-3">
            <div>
              <Label>City</Label>
              <input
                className={inputCls()}
                placeholder="Columbus"
                value={form.city}
                onChange={set("city")}
              />
              {errors.city && <p className="text-caption-1 mt-1 text-danger">{errors.city}</p>}
            </div>
            <div>
              <Label>State</Label>
              <select className={inputCls("appearance-none")} value={form.state} onChange={set("state")}>
                <option value="">Select</option>
                {US_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              {errors.state && <p className="text-caption-1 mt-1 text-danger">{errors.state}</p>}
            </div>
          </div>

          <div>
            <Label>ZIP Code</Label>
            <input
              className={inputCls()}
              placeholder="43213"
              value={form.zip}
              onChange={set("zip")}
              inputMode="numeric"
              maxLength={10}
            />
            {errors.zip && <p className="text-caption-1 mt-1 text-danger">{errors.zip}</p>}
          </div>

          {/* GPS coordinates (alternative to address) */}
          <div className="mt-4 border-t border-hairline pt-4">
            <p className="text-caption-1 mb-3 text-label-tertiary">
              <strong className="text-label-secondary">Or enter GPS coordinates</strong>
              {" "}— provide latitude + longitude instead of (or in addition to) an address.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Latitude</Label>
                <input
                  className={inputCls()}
                  placeholder="39.9612"
                  type="number"
                  step="any"
                  min="-90"
                  max="90"
                  value={form.latitude}
                  onChange={set("latitude")}
                />
                {errors.latitude && (
                  <p className="text-caption-1 mt-1 text-danger">{errors.latitude}</p>
                )}
              </div>
              <div>
                <Label>Longitude</Label>
                <input
                  className={inputCls()}
                  placeholder="-82.9988"
                  type="number"
                  step="any"
                  min="-180"
                  max="180"
                  value={form.longitude}
                  onChange={set("longitude")}
                />
                {errors.longitude && (
                  <p className="text-caption-1 mt-1 text-danger">{errors.longitude}</p>
                )}
              </div>
            </div>
            {errors.address && !form.address.trim() && (
              <p className="text-caption-1 mt-2 text-danger">{errors.address}</p>
            )}
          </div>
        </div>

        {/* Site Details */}
        <div className="glass mb-4 rounded-2xl border border-hairline p-5">
          <p className="text-callout mb-4 font-semibold text-label-primary">Site Details</p>

          <div className="mb-4">
            <Label>Target Workload *</Label>
            <select
              className={inputCls("appearance-none")}
              value={form.target_workload}
              onChange={set("target_workload")}
            >
              {WORKLOAD_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {errors.target_workload && (
              <p className="text-caption-1 mt-1 text-danger">{errors.target_workload}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Parcel Size (acres)</Label>
              <input
                className={inputCls()}
                placeholder="250"
                type="number"
                min="0"
                step="0.1"
                value={form.acres}
                onChange={set("acres")}
              />
            </div>
            <div>
              <Label>Available Power (MW)</Label>
              <input
                className={inputCls()}
                placeholder="100"
                type="number"
                min="0"
                step="1"
                value={form.target_mw}
                onChange={set("target_mw")}
              />
            </div>
          </div>

          <div className="mt-4">
            <Label>Fiber Providers Present</Label>
            <input
              className={inputCls()}
              placeholder="AT&T, Lumen, Zayo"
              value={form.fiber_providers}
              onChange={set("fiber_providers")}
            />
          </div>

          <div className="mt-4">
            <Label>Zoning Status</Label>
            <input
              className={inputCls()}
              placeholder="M-2 Industrial, pending rezoning"
              value={form.zoning_status}
              onChange={set("zoning_status")}
            />
          </div>

          <div className="mt-4">
            <Label>Flood Zone</Label>
            <select
              className={inputCls("appearance-none")}
              value={form.flood_zone}
              onChange={set("flood_zone")}
            >
              <option value="no">No</option>
              <option value="yes">Yes</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
        </div>

        {/* Notes + Drive + Docs */}
        <div className="glass mb-4 rounded-2xl border border-hairline p-5">
          <p className="text-callout mb-4 font-semibold text-label-primary">Additional Notes</p>

          <div className="mb-4">
            <textarea
              rows={4}
              className={inputCls("resize-none")}
              placeholder="Any other context about this site…"
              value={form.notes}
              onChange={set("notes")}
            />
          </div>

          {/* Google Drive Folder */}
          <div className="mb-4">
            <Label>Google Drive Folder (optional)</Label>
            <div className="relative">
              <FolderOpen className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-label-tertiary" />
              <input
                className={inputCls("pl-9")}
                placeholder="https://drive.google.com/drive/folders/…"
                value={form.drive_folder_url}
                onChange={set("drive_folder_url")}
                type="url"
                inputMode="url"
              />
            </div>
            <p className="text-caption-1 mt-1 text-label-quaternary">
              Share a Drive folder with site docs — the research agents will index it.
            </p>
          </div>

          {/* File Upload */}
          <div>
            <Label>Supporting Documents (optional)</Label>
            <label
              className={cn(
                "flex w-full cursor-pointer flex-col items-center justify-center gap-2",
                "rounded-xl border border-dashed border-hairline bg-bg-elevated px-4 py-5",
                "transition-colors hover:border-accent/50 hover:bg-accent/5",
              )}
            >
              <Paperclip className="h-5 w-5 text-label-tertiary" />
              <span className="text-caption-1 text-center text-label-secondary">
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
            <p className="text-caption-1 mt-1 text-label-quaternary">
              Phase 1 ESA, geotech reports, utility LOIs, title docs, appraisals
            </p>
            {uploadFiles.length > 0 && (
              <ul className="mt-2 space-y-1">
                {uploadFiles.map((f, i) => (
                  <li
                    key={i}
                    className="text-caption-1 flex items-center justify-between gap-2 text-label-secondary"
                  >
                    <span className="truncate">{f.name}</span>
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="text-caption-1 shrink-0 text-label-tertiary transition-colors hover:text-danger"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isPending}
          className={cn(
            "text-body w-full rounded-2xl bg-accent py-3.5 font-semibold text-white",
            "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
            isPending && "cursor-not-allowed opacity-60",
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

        {createSite.isError && !isPending && (
          <p className="text-caption-1 mt-2 text-center text-danger">
            {(createSite.error as Error)?.message ?? "Submission failed."}
          </p>
        )}
      </form>
    </MobileShell>
  );
}
