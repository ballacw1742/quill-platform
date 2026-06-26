export default function Login() {
  return (
    <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center text-white">
      <div className="max-w-sm w-full px-6">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-500/20 mb-4">
            <svg className="w-7 h-7 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white mb-1">Quill PMO</h1>
          <p className="text-slate-400 text-sm">Sign in to continue</p>
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-4">
          <button
            className="w-full flex items-center justify-center gap-3 bg-white text-slate-900 rounded-lg px-4 py-3 font-medium hover:bg-slate-100 transition-colors"
            onClick={() => alert('Google Sign-In not yet configured')}
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google
          </button>

          <div className="text-center">
            <p className="text-xs text-slate-500">
              Authentication will be connected to the Quill API
            </p>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-slate-600">
          Quill PMO Platform • Powered by Firebase
        </p>
      </div>
    </div>
  )
}
