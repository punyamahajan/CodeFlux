import React, { useEffect, useState } from 'react'
import { api, ExplainResult, NarrationResult } from '../api'
import { X, Sparkles, HelpCircle, AlertTriangle } from 'lucide-react'

interface WhyPanelProps {
  kind: string
  id: string
  onClose: () => void
}

export const WhyPanel: React.FC<WhyPanelProps> = ({ kind, id, onClose }) => {
  const [data, setData] = useState<ExplainResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [narration, setNarration] = useState<NarrationResult | null>(null)
  const [narrating, setNarrating] = useState(false)
  const [showFacts, setShowFacts] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    api
      .explain(kind, id)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [kind, id])

  const handleNarrate = async () => {
    setNarrating(true)
    try {
      const res = await api.narrate(kind, id)
      setNarration(res)
    } catch (err: any) {
      alert(`Narration failed: ${err.message}`)
    } finally {
      setNarrating(false)
    }
  }

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-slate-900 border-l border-slate-800 shadow-2xl flex flex-col p-6 overflow-y-auto">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div className="flex items-center space-x-2">
          <HelpCircle className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-semibold text-white capitalize">Why did this happen?</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
          aria-label="Close why panel"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="mt-4 flex-1">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 space-y-3">
            <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-slate-400">Loading explanation facts...</p>
          </div>
        )}

        {error && (
          <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-300 text-sm flex items-start space-x-3">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Could not load explanation</p>
              <p className="text-xs text-rose-400/80 mt-1">{error}</p>
            </div>
          </div>
        )}

        {data && (
          <div className="space-y-6">
            <div className="p-4 bg-emerald-950/40 border border-emerald-800/40 rounded-xl">
              <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">Headline</span>
              <p className="text-base font-medium text-slate-100 mt-1">{data.headline}</p>
            </div>

            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Key Factors</h3>
              <ul className="space-y-2">
                {data.bullets.map((bullet, idx) => (
                  <li key={idx} className="flex items-start text-sm text-slate-300 space-x-2">
                    <span className="text-emerald-500 mt-1">•</span>
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* AI Narration card */}
            <div className="p-4 bg-slate-800/60 border border-slate-700/60 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-purple-400 flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>AI Narration (Guard Enforced)</span>
                </span>
                {narration && (
                  <span className="text-xs text-slate-400">
                    {narration.cached ? 'cached' : narration.guard ? 'fallback' : 'fresh'}
                  </span>
                )}
              </div>

              {narration?.narration ? (
                <div className="text-sm text-slate-200 bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                  <p>{narration.narration}</p>
                  {narration.guard === 'rejected_invented_numbers' && (
                    <p className="text-xs text-amber-400 mt-2 flex items-center space-x-1">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      <span>Raw model output attempted to introduce unverified numbers; reverted to deterministic explanation.</span>
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-slate-400">
                  Generate a plain-English narrative of these facts. Any reply with unverified numbers is strictly discarded.
                </p>
              )}

              <button
                onClick={handleNarrate}
                disabled={narrating}
                className="w-full flex items-center justify-center space-x-2 py-2 px-3 bg-purple-600/80 hover:bg-purple-600 text-white rounded-lg text-xs font-medium transition disabled:opacity-50"
              >
                <Sparkles className="w-4 h-4" />
                <span>{narrating ? 'Generating narration...' : narration ? 'Re-narrate' : 'Explain with AI Narration'}</span>
              </button>
            </div>

            {/* Raw facts accordion */}
            <div>
              <button
                onClick={() => setShowFacts(!showFacts)}
                className="text-xs text-slate-400 hover:text-slate-200 transition underline underline-offset-2"
              >
                {showFacts ? 'Hide raw facts JSON' : 'Show raw facts JSON'}
              </button>
              {showFacts && (
                <pre className="mt-2 p-3 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto max-h-60">
                  {JSON.stringify(data.facts, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="pt-4 border-t border-slate-800 mt-auto">
        <p className="text-xs text-slate-500 text-center">
          OmniKey Explain Engine • Facts schema v1 • Strictly verified numbers
        </p>
      </div>
    </div>
  )
}
