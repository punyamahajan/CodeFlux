import React, { useState } from 'react'
import { api } from '../api'
import { Swords, Play, AlertCircle, Award, Sparkles, XCircle } from 'lucide-react'
import { formatMicroUSD } from '../utils'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const ArenaCompare: React.FC = () => {
  const [prompt, setPrompt] = useState('Compare the pros and cons of SQLite vs PostgreSQL for local development in 2 bullet points.')
  const [modelInputs, setModelInputs] = useState(['fast', 'smart', 'gemini-tier'])
  const [judge, setJudge] = useState(true)
  const [judgeModel, setJudgeModel] = useState('fast')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
  const [whyRunId, setWhyRunId] = useState<string | null>(null)

  const handleAddModel = () => {
    if (modelInputs.length < 4) {
      setModelInputs([...modelInputs, 'llama-3.3-70b-versatile'])
    }
  }

  const handleRemoveModel = (index: number) => {
    setModelInputs(modelInputs.filter((_, i) => i !== index))
  }

  const handleUpdateModel = (index: number, val: string) => {
    const updated = [...modelInputs]
    updated[index] = val
    setModelInputs(updated)
  }

  const handleRun = async () => {
    const filtered = modelInputs.map((m) => m.trim()).filter(Boolean)
    if (filtered.length === 0) return
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const data = await api.arenaCompare({
        prompt: prompt.trim(),
        models: filtered,
        judge,
        judge_model: judgeModel,
      })
      setResult(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center space-x-2">
            <div className="p-1.5 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600">
              <Swords className="w-5 h-5" />
            </div>
            <span>Compare Arena</span>
          </h1>
          <p className="text-xs text-slate-500">
            Run up to 4 models simultaneously with no fallback. Automated AI judging and code-calculated rankings.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Input controls */}
      <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-5 shadow-xs">
        <div>
          <label className="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-1.5">
            Test Prompt
          </label>
          <textarea
            rows={3}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Enter prompt to evaluate across models..."
            className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
              Models to Compare ({modelInputs.length}/4)
            </label>
            {modelInputs.length < 4 && (
              <button
                type="button"
                onClick={handleAddModel}
                className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold cursor-pointer"
              >
                + Add Model
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {modelInputs.map((mod, idx) => (
              <div key={idx} className="flex items-center space-x-2">
                <input
                  type="text"
                  value={mod}
                  onChange={(e) => handleUpdateModel(idx, e.target.value)}
                  className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-indigo-700 font-mono font-semibold focus:outline-none focus:border-indigo-500"
                />
                {modelInputs.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveModel(idx)}
                    className="p-1 text-slate-400 hover:text-rose-600 cursor-pointer text-sm font-bold"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-slate-100">
          <div className="flex items-center space-x-4">
            <label className="flex items-center space-x-2 text-xs text-slate-700 cursor-pointer font-medium">
              <input
                type="checkbox"
                checked={judge}
                onChange={(e) => setJudge(e.target.checked)}
                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span>Enable AI Judge Evaluation</span>
            </label>
            {judge && (
              <div className="flex items-center space-x-2 text-xs">
                <span className="text-slate-500">Judge Model:</span>
                <input
                  type="text"
                  value={judgeModel}
                  onChange={(e) => setJudgeModel(e.target.value)}
                  className="px-2.5 py-1 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-indigo-700 font-semibold"
                />
              </div>
            )}
          </div>

          <button
            onClick={handleRun}
            disabled={loading}
            className="px-6 py-2.5 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-2 shadow-md shadow-indigo-500/25 transition disabled:opacity-50 cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{loading ? 'Evaluating in Parallel...' : 'Run Arena Comparison'}</span>
          </button>
        </div>
      </div>

      {/* Results view */}
      {result && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <h2 className="text-lg font-bold text-slate-900">Comparison Results</h2>
              {result.run_id && (
                <WhyButton onClick={() => setWhyRunId(result.run_id)} label="Why this ranking?" />
              )}
            </div>

            {result.ranking && result.ranking.length > 0 && (
              <div className="flex items-center space-x-2 bg-indigo-50 border border-indigo-200/80 px-3.5 py-1.5 rounded-xl text-xs text-indigo-800 shadow-xs">
                <Award className="w-4 h-4 text-indigo-600" />
                <span className="font-semibold">Winner: {result.ranking[0]}</span>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {result.models.map((m: any, idx: number) => {
              const rankPos = result.ranking?.indexOf(m.model)
              return (
                <div
                  key={idx}
                  className={`p-5 bg-white border rounded-2xl space-y-4 shadow-xs hover:shadow-md transition flex flex-col ${
                    rankPos === 0
                      ? 'border-indigo-400 shadow-md shadow-indigo-100/50 ring-1 ring-indigo-400/30'
                      : 'border-slate-200/80'
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div>
                      <span className="font-bold text-sm text-slate-900">{m.model}</span>
                      <span className="text-[10px] text-slate-500 block uppercase font-mono">{m.provider}</span>
                    </div>
                    {rankPos !== -1 && rankPos !== undefined && (
                      <span className="px-2.5 py-0.5 bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-semibold rounded-full">
                        #{rankPos + 1}
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center text-xs bg-slate-50 p-2.5 rounded-xl border border-slate-200/60">
                    <div>
                      <span className="text-[10px] text-slate-500 block">Latency</span>
                      <span className="font-mono text-slate-800 font-medium">{m.latency_ms ?? 0} ms</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block">Tokens</span>
                      <span className="font-mono text-slate-800 font-medium">{(m.prompt_tokens || 0) + (m.completion_tokens || 0)}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block">Cost</span>
                      <span className="font-mono text-indigo-700 font-semibold">{formatMicroUSD(m.cost_micro || 0)}</span>
                    </div>
                  </div>

                  {/* Judge scores */}
                  {m.accuracy !== undefined && (
                    <div className="p-3 bg-purple-50/60 border border-purple-200/70 rounded-xl space-y-1.5 text-xs">
                      <div className="flex items-center justify-between text-purple-900 font-semibold text-[11px]">
                        <span className="flex items-center space-x-1">
                          <Sparkles className="w-3.5 h-3.5 text-purple-600" />
                          <span>AI-judged Score</span>
                        </span>
                        <span className="font-mono font-bold">{m.accuracy + m.clarity + m.completeness}/30</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1 text-[11px] text-purple-800">
                        <span>Acc: {m.accuracy}/10</span>
                        <span>Cla: {m.clarity}/10</span>
                        <span>Cmp: {m.completeness}/10</span>
                      </div>
                      {m.judge_reason && (
                        <p className="text-[11px] text-purple-700/90 italic mt-1 leading-relaxed">"{m.judge_reason}"</p>
                      )}
                    </div>
                  )}

                  <div className="flex-1 bg-slate-50 p-3 rounded-xl border border-slate-200/80 text-xs text-slate-800 overflow-y-auto max-h-56 leading-relaxed">
                    {m.error ? (
                      <p className="text-rose-600 flex items-center space-x-1.5">
                        <XCircle className="w-4 h-4 flex-shrink-0" />
                        <span>Failed: {m.error}</span>
                      </p>
                    ) : (
                      m.output
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {whyRunId && (
        <WhyPanel
          kind="compare"
          id={whyRunId}
          onClose={() => setWhyRunId(null)}
        />
      )}
    </div>
  )
}
