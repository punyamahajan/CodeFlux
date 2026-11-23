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
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-white border-l border-slate-200 shadow-2xl flex flex-col p-6 overflow-y-auto">
      <div className="flex items-center justify-between pb-4 border-b border-slate-100">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
            <HelpCircle className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900 capitalize">Why did this happen?</h2>
            <p className="text-[11px] text-slate-500">Deterministic plain-English breakdown of this event</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-100 transition cursor-pointer"
          aria-label="Close why panel"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="mt-4 flex-1">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 space-y-3">
            <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs text-slate-500 font-medium">Loading explanation facts...</p>
          </div>
        )}

        {error && (
          <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 text-xs flex items-start space-x-3">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-600" />
            <div>
              <p className="font-semibold text-rose-900">Could not load explanation</p>
              <p className="text-xs text-rose-700 mt-1">{error}</p>
            </div>
          </div>
        )}

        {data && (
          <div className="space-y-6">
            <div className="p-4 bg-gradient-to-br from-indigo-50/90 to-violet-50/90 border border-indigo-100/80 rounded-xl">
              <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-700">Headline</span>
              <p className="text-sm font-semibold text-slate-900 mt-1">{data.headline}</p>
            </div>

            <div>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-3">Key Factors</h3>
              <ul className="space-y-2.5">
                {data.bullets.map((bullet, idx) => (
                  <li key={idx} className="flex items-start text-xs text-slate-700 space-x-2.5 leading-relaxed">
                    <span className="text-indigo-600 font-bold mt-0.5 text-sm">•</span>
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* AI Narration card */}
            <div className="p-4 bg-slate-50 border border-slate-200/80 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-purple-700 flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>AI Narration (Guard Enforced)</span>
                </span>
                {narration && (
                  <span className="text-[10px] px-2 py-0.5 bg-purple-100 text-purple-700 font-semibold rounded-full">
                    {narration.cached ? 'cached' : narration.guard ? 'fallback' : 'verified'}
                  </span>
                )}
              </div>

              {narration?.narration ? (
                <div className="text-xs text-slate-800 bg-white p-3 rounded-lg border border-slate-200/80 leading-relaxed">
                  <p>{narration.narration}</p>
                  {narration.guard === 'rejected_invented_numbers' && (
                    <p className="text-[11px] text-amber-800 mt-2 flex items-center space-x-1 font-medium">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                      <span>Raw model output attempted to introduce unverified numbers; reverted to deterministic explanation.</span>
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-slate-500">
                  Generate a plain-English narrative of these facts. Any reply with unverified numbers is strictly discarded.
                </p>
              )}

              <button
                onClick={handleNarrate}
                disabled={narrating}
                className="w-full flex items-center justify-center space-x-2 py-2 px-3 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-lg text-xs font-semibold shadow-xs transition disabled:opacity-50 cursor-pointer"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>{narrating ? 'Generating narration...' : narration ? 'Re-narrate' : 'Explain with AI Narration'}</span>
              </button>
            </div>

            {/* Raw facts accordion */}
            <div>
              <button
                onClick={() => setShowFacts(!showFacts)}
                className="text-xs font-medium text-slate-500 hover:text-indigo-600 transition underline underline-offset-2 cursor-pointer"
              >
                {showFacts ? 'Hide raw facts JSON' : 'Show raw facts JSON'}
              </button>
              {showFacts && (
                <pre className="mt-2 p-3 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-emerald-400 overflow-x-auto max-h-60">
                  {JSON.stringify(data.facts, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="pt-4 border-t border-slate-100 mt-auto">
        <p className="text-[11px] text-slate-400 text-center">
          OmniKey Explain Engine • Facts schema v1 • Strictly verified numbers
        </p>
      </div>
    </div>
  )
}
