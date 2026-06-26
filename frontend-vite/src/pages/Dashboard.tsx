export default function Dashboard() {
  return (
    <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center text-white">
      <div className="max-w-lg w-full px-6 text-center">
        <div className="mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-500/20 mb-4">
            <svg className="w-8 h-8 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white mb-2">Quill PMO Platform</h1>
          <p className="text-slate-400 text-lg">Dashboard coming soon</p>
        </div>
        <div className="rounded-xl bg-slate-800 border border-slate-700 p-6 text-left space-y-3">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-blue-500"></div>
            <span className="text-slate-300 text-sm">Approval Queue</span>
            <span className="ml-auto text-xs text-slate-500">coming soon</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-slate-600"></div>
            <span className="text-slate-300 text-sm">Site Pipeline</span>
            <span className="ml-auto text-xs text-slate-500">coming soon</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-slate-600"></div>
            <span className="text-slate-300 text-sm">Contract Manager</span>
            <span className="ml-auto text-xs text-slate-500">coming soon</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-slate-600"></div>
            <span className="text-slate-300 text-sm">Audit Log</span>
            <span className="ml-auto text-xs text-slate-500">coming soon</span>
          </div>
        </div>
        <p className="mt-6 text-xs text-slate-600">
          Quill Platform • Firebase Hosting
        </p>
      </div>
    </div>
  )
}
