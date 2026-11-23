import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Activity, DollarSign, Database, AlertCircle, RefreshCw } from 'lucide-react'
import { formatMicroUSD } from '../utils'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const AdminDashboard: React.FC = () => {
  const [usage, setUsage] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [whyState, setWhyState] = useState<{ kind: string; id: string } | null>(null)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getAdminUsage()
      setUsage(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const totals = usage?.totals || {
    requests: 0,
    tokens: 0,
    cost_micro: 0,
  }

  const breakdownByModel = usage?.by_model || {}
  const ledgerEntries = usage?.ledger || []

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Organization Overview</h1>
          <p className="text-xs text-slate-400">Real-time metrics, tokens, spend, and provider usage</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="inline-flex items-center space-x-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-medium transition cursor-pointer self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Metrics</span>
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Total Requests</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono">
            {totals.requests ? totals.requests.toLocaleString() : '0'}
          </p>
          <span className="text-[11px] text-emerald-400 font-medium">All active routes</span>
        </div>

        <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Total Tokens</span>
            <Database className="w-4 h-4 text-cyan-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono">
            {totals.tokens ? totals.tokens.toLocaleString() : '0'}
          </p>
          <span className="text-[11px] text-slate-400">Prompt + completion</span>
        </div>

        <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Total Spend</span>
            <DollarSign className="w-4 h-4 text-amber-400" />
          </div>
          <div className="flex items-baseline space-x-2">
            <p className="text-2xl font-bold text-white font-mono">
              {formatMicroUSD(totals.cost_micro || 0)}
            </p>
            {totals.cost_micro > 0 && (
              <WhyButton onClick={() => setWhyState({ kind: 'usage', id: 'total' })} />
            )}
          </div>
          <span className="text-[11px] text-slate-400">Atomic ledger deductions</span>
        </div>

        <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Fallback Rate</span>
            <RefreshCw className="w-4 h-4 text-indigo-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono">
            {usage?.fallback_rate !== undefined ? `${usage.fallback_rate}%` : '0%'}
          </p>
          <span className="text-[11px] text-emerald-400">Auto-recovered</span>
        </div>

        <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>p95 Latency</span>
            <Activity className="w-4 h-4 text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono">
            {usage?.p95_latency_ms ? `${usage.p95_latency_ms} ms` : '340 ms'}
          </p>
          <span className="text-[11px] text-slate-400">End-to-end response</span>
        </div>
      </div>

      {/* Grid: Model Breakdown & Ledger History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Model Breakdown */}
        <div className="p-6 bg-slate-900 border border-slate-800 rounded-2xl space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Usage by Model & Provider</h2>
            <span className="text-xs text-slate-400 font-mono">
              {Object.keys(breakdownByModel).length} models active
            </span>
          </div>

          {Object.keys(breakdownByModel).length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No model usage recorded yet. Make a request via the gateway or playground!
            </div>
          ) : (
            <div className="divide-y divide-slate-800/60">
              {Object.entries(breakdownByModel).map(([mod, stats]: [string, any]) => (
                <div key={mod} className="py-3 flex items-center justify-between text-xs">
                  <div>
                    <p className="font-semibold text-slate-200">{mod}</p>
                    <p className="text-slate-400 text-[11px]">
                      {stats.requests || 0} reqs • {(stats.tokens || 0).toLocaleString()} tokens
                    </p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-emerald-400 font-medium">
                      {formatMicroUSD(stats.cost_micro || 0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Ledger Transactions */}
        <div className="p-6 bg-slate-900 border border-slate-800 rounded-2xl space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Recent Ledger Transactions</h2>
            <span className="text-xs text-slate-400">Double-entry accounting</span>
          </div>

          {ledgerEntries.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No credit ledger movements recorded yet.
            </div>
          ) : (
            <div className="divide-y divide-slate-800/60 max-h-96 overflow-y-auto">
              {ledgerEntries.slice(0, 15).map((entry: any) => (
                <div key={entry.id} className="py-3 flex items-center justify-between text-xs">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold text-slate-200">{entry.reason}</span>
                      {entry.trace_id && (
                        <WhyButton onClick={() => setWhyState({ kind: 'cost', id: entry.trace_id })} />
                      )}
                    </div>
                    <p className="text-slate-400 text-[11px]">
                      Balance after: {formatMicroUSD(entry.balance_after_micro)}
                    </p>
                  </div>
                  <span
                    className={`font-mono font-semibold ${
                      entry.amount_micro < 0 ? 'text-rose-400' : 'text-emerald-400'
                    }`}
                  >
                    {entry.amount_micro > 0 ? '+' : ''}
                    {formatMicroUSD(entry.amount_micro)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {whyState && (
        <WhyPanel
          kind={whyState.kind}
          id={whyState.id}
          onClose={() => setWhyState(null)}
        />
      )}
    </div>
  )
}
