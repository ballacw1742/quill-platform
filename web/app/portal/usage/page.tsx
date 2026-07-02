"use client";

/**
 * /portal/usage — Usage Placeholder (Sprint 4B)
 *
 * Usage reporting is not yet built. Shows campus context + stub message.
 */

import * as React from "react";
import { BarChart2, Clock } from "lucide-react";
import { usePortalUsage, usePortalMe } from "@/lib/api";

export default function PortalUsagePage() {
  const { data: usage } = usePortalUsage();
  const { data: me } = usePortalMe();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Usage</h1>

      {/* Context card */}
      {(me?.linked_campus_name || usage?.contracted_mw) && (
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Campus & Contract</h2>
          <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <dt className="text-xs text-gray-400 mb-0.5">Campus</dt>
              <dd className="text-sm font-semibold text-gray-900">
                {me?.linked_campus_name ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 mb-0.5">Contracted Capacity</dt>
              <dd className="text-sm font-semibold text-gray-900">
                {usage?.contracted_mw != null ? `${usage.contracted_mw} MW` : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 mb-0.5">Status</dt>
              <dd className="text-sm font-semibold text-gray-900 capitalize">
                {usage?.status ?? "—"}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {/* Coming soon banner */}
      <div className="bg-blue-50 border border-blue-200 rounded-2xl p-8 text-center">
        <div className="w-14 h-14 bg-blue-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <BarChart2 className="w-7 h-7 text-blue-500" />
        </div>
        <h2 className="text-lg font-semibold text-gray-900 mb-2">
          Usage reporting coming soon
        </h2>
        <p className="text-sm text-gray-600 max-w-md mx-auto">
          Detailed power usage, utilization metrics, and consumption reports are currently in
          development. Contact your account manager for usage data in the meantime.
        </p>
        <div className="mt-5 flex items-center justify-center gap-2 text-xs text-blue-500">
          <Clock className="w-3.5 h-3.5" />
          <span>Estimated availability: Q3 2026</span>
        </div>
      </div>
    </div>
  );
}
