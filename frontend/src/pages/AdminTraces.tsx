import React, { useEffect, useState } from 'react'
import { api, RequestTrace } from '../api'
import { Activity, RefreshCw, AlertCircle } from 'lucide-react'
import { formatMicroUSD } from '../utils'
import { AttemptTimeline } from '../components/AttemptTimeline'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const AdminTraces: React.FC = () => {
  const [traces, setTraces] = useState<RequestTrace[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedTrace, setSelectedTrace] = useState<RequestTrace | null>(null)
  const [whyTraceId, setWhyTraceId] = useState<string | null>(null)

  const loadTraces = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getTraces()
      setTraces(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTraces()
  }, [])

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Activity className="w-6 h-6 text-emerald-400" />
            <span>Request Traces & Audit Log</span>
          </h1>
          <p className="text-xs text-slate-400">
            Every gateway request stores structured facts: attempts, token usage, latency, and costs.
          </p>
        </div>
        <button
          onClick={loadTraces}
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trace List */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 sticky top-0 border-b border-slate-800 text-slate-400 uppercase tracking-wider font-semibold z-10">
                <tr>
                  <th className="py-3.5 px-4">Trace ID</th>
                  <th className="py-3.5 px-4">Model & Provider</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4">Latency</th>
                  <th className="py-3.5 px-4">Cost</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {traces.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      No request traces logged yet.
                    </td>
                  </tr>
                ) : (
                  traces.map((tr) => (
                    <tr
                      key={tr.id}
                      onClick={() => setSelectedTrace(tr)}
                      className={`hover:bg-slate-800/40 transition cursor-pointer ${
                        selectedTrace?.id === tr.id ? 'bg-slate-800/50' : ''
                      }`}
                    >
                      <td className="py-3.5 px-4 font-mono text-emerald-400">{tr.id.slice(0, 14)}...</td>
                      <td className="py-3.5 px-4">
                        <span className="font-semibold text-slate-100">{tr.model || 'default'}</span>
                        <span className="text-[11px] text-slate-400 block uppercase">{tr.provider || 'unknown'}</span>
                      </td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            tr.status_code && tr.status_code < 400
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                          }`}
                        >
                          {tr.status_code || 200}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 font-mono">{tr.latency_ms ?? 0} ms</td>
                      <td className="py-3.5 px-4 font-mono text-emerald-400">
                        {formatMicroUSD(tr.cost_micro)}
                      </td>
                      <td className="py-3.5 px-4 text-right space-x-1.5">
                        <WhyButton onClick={() => setWhyTraceId(tr.id)} />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Trace Detail & Attempt Timeline */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5 shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-semibold text-white">Trace Details</h3>
            {selectedTrace && (
              <WhyButton
                onClick={() => setWhyTraceId(selectedTrace.id)}
                label="Explain Trace"
              />
            )}
          </div>

          {selectedTrace ? (
            <div className="space-y-4 text-xs">
              <div className="space-y-1">
                <span className="text-[11px] text-slate-400 uppercase font-semibold">Trace ID</span>
                <p className="font-mono text-emerald-400 break-all">{selectedTrace.id}</p>
              </div>

              <div className="grid grid-cols-2 gap-2 text-slate-300">
                <div>
                  <span className="text-slate-400 block">Prompt Tokens:</span>
                  <span className="font-mono">{selectedTrace.prompt_tokens}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Completion Tokens:</span>
                  <span className="font-mono">{selectedTrace.completion_tokens}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Charged Cost:</span>
                  <span className="font-mono text-emerald-400">{formatMicroUSD(selectedTrace.cost_micro)}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Timestamp:</span>
                  <span>{new Date(selectedTrace.created_at).toLocaleTimeString()}</span>
                </div>
              </div>

              {/* Waterfall Attempt Timeline */}
              <div className="pt-2 border-t border-slate-800 space-y-2">
                <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  Routing Waterfall Timeline
                </h4>
                <AttemptTimeline attempts={selectedTrace.facts?.attempts || []} />
              </div>
            </div>
          ) : (
            <div className="py-16 text-center text-xs text-slate-500">
              Select a trace row on the left to view its complete timeline and facts.
            </div>
          )}
        </div>
      </div>

      {whyTraceId && (
        <WhyPanel
          kind="trace"
          id={whyTraceId}
          onClose={() => setWhyTraceId(null)}
        />
      )}
    </div>
  )
}
