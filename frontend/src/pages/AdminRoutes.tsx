import React, { useEffect, useState } from 'react'
import { api, RouteConfig } from '../api'
import { Route, RefreshCw, AlertCircle } from 'lucide-react'

export const AdminRoutes: React.FC = () => {
  const [routes, setRoutes] = useState<RouteConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadRoutes = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getRoutes()
      setRoutes(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRoutes()
  }, [])

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Route className="w-6 h-6 text-emerald-400" />
            <span>Fallback Routes & Provider Chains</span>
          </h1>
          <p className="text-xs text-slate-400">
            Configure candidate priority, load balancing strategies (priority, round-robin, least-latency), and task tags.
          </p>
        </div>
        <button
          onClick={loadRoutes}
          className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition self-start sm:self-auto"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {routes.length === 0 ? (
        <div className="p-12 text-center bg-slate-900 border border-slate-800 rounded-2xl text-slate-500 text-xs">
          Loading configured routes from routes.yaml...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6">
          {routes.map((rt) => (
            <div key={rt.alias} className="p-6 bg-slate-900 border border-slate-800 rounded-2xl space-y-4 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
                <div className="flex items-center space-x-3">
                  <span className="px-2.5 py-1 bg-emerald-500/20 text-emerald-400 rounded-lg text-xs font-mono font-bold">
                    {rt.alias}
                  </span>
                  <span className="text-xs text-slate-300 capitalize font-medium">
                    Strategy: {rt.strategy}
                  </span>
                  {rt.task_tag && (
                    <span className="text-xs text-purple-400 bg-purple-500/10 border border-purple-500/20 px-2 py-0.5 rounded-full font-mono">
                      tag: {rt.task_tag}
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-3 text-xs text-slate-400">
                  <span>Timeout: {rt.total_timeout_seconds}s</span>
                  <span>PII: {rt.pii_redaction ? 'Redacted' : 'Pass-through'}</span>
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Candidate Fallback Sequence
                </h4>
                <div className="space-y-2">
                  {rt.candidates.map((cand, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl flex items-center justify-between text-xs"
                    >
                      <div className="flex items-center space-x-3">
                        <span className="w-5 h-5 rounded-full bg-slate-800 text-slate-300 font-bold text-[10px] flex items-center justify-center">
                          {idx + 1}
                        </span>
                        <div>
                          <span className="font-semibold text-white uppercase">{cand.provider}</span>
                          <span className="text-slate-400 font-mono ml-2">({cand.model})</span>
                        </div>
                      </div>
                      <div className="flex items-center space-x-4 text-slate-400 text-[11px]">
                        {cand.timeout_seconds && <span>timeout: {cand.timeout_seconds}s</span>}
                        {cand.weight && <span>weight: {cand.weight}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
