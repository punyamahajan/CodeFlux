import React, { useState } from 'react'
import { api } from '../api'
import { Swords, Play, AlertCircle, Award, MessagesSquare } from 'lucide-react'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const ArenaDebate: React.FC = () => {
  const [topic, setTopic] = useState('Should AI code generators be required to attribute their training data sources?')
  const [modelA, setModelA] = useState('fast')
  const [modelB, setModelB] = useState('gemini-tier')
  const [judgeModel, setJudgeModel] = useState('smart')
  const [rounds, setRounds] = useState(1)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
  const [whyRunId, setWhyRunId] = useState<string | null>(null)

  const handleRun = async () => {
    if (!topic.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const data = await api.arenaDebate({
        topic: topic.trim(),
        model_a: modelA.trim(),
        model_b: modelB.trim(),
        judge_model: judgeModel.trim(),
        rounds,
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
            <div className="p-1.5 rounded-xl bg-purple-50 border border-purple-100 text-purple-600">
              <Swords className="w-5 h-5" />
            </div>
            <span>Debate Arena</span>
          </h1>
          <p className="text-xs text-slate-500">
            Oxford-style AI debates. Two models take opposing sides across structured rounds with a 120-word turn cap and AI judging.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Debate Setup Controls */}
      <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-5 shadow-xs">
        <div>
          <label className="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-1.5">
            Debate Motion / Topic
          </label>
          <input
            type="text"
            required
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Is open source AI safer than proprietary AI?"
            className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div>
            <label className="text-xs font-semibold text-emerald-700 uppercase tracking-wider block mb-1">
              Side FOR (Proponent)
            </label>
            <input
              type="text"
              value={modelA}
              onChange={(e) => setModelA(e.target.value)}
              className="w-full px-3 py-2 bg-emerald-50/50 border border-emerald-200 rounded-xl text-xs font-mono text-emerald-800 font-semibold focus:outline-none focus:border-emerald-500"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-rose-700 uppercase tracking-wider block mb-1">
              Side AGAINST (Opponent)
            </label>
            <input
              type="text"
              value={modelB}
              onChange={(e) => setModelB(e.target.value)}
              className="w-full px-3 py-2 bg-rose-50/50 border border-rose-200 rounded-xl text-xs font-mono text-rose-800 font-semibold focus:outline-none focus:border-rose-500"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-purple-700 uppercase tracking-wider block mb-1">
              Judge Model
            </label>
            <input
              type="text"
              value={judgeModel}
              onChange={(e) => setJudgeModel(e.target.value)}
              className="w-full px-3 py-2 bg-purple-50/50 border border-purple-200 rounded-xl text-xs font-mono text-purple-800 font-semibold focus:outline-none focus:border-purple-500"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-1">
              Rounds (max 3)
            </label>
            <select
              value={rounds}
              onChange={(e) => setRounds(parseInt(e.target.value, 10))}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-900 focus:outline-none focus:border-purple-500 font-medium"
            >
              <option value={1}>1 Round</option>
              <option value={2}>2 Rounds (Default)</option>
              <option value={3}>3 Rounds (Full Debate)</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end pt-3 border-t border-slate-100">
          <button
            onClick={handleRun}
            disabled={loading}
            className="px-6 py-2.5 bg-gradient-to-r from-purple-600 via-violet-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-2 shadow-md shadow-purple-500/25 transition disabled:opacity-50 cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{loading ? 'Running Multi-Round Debate...' : 'Start Oxford Debate'}</span>
          </button>
        </div>
      </div>

      {/* Results view */}
      {result && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 bg-gradient-to-r from-indigo-50/70 via-purple-50/70 to-pink-50/70 border border-purple-200 rounded-2xl shadow-xs">
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <Award className="w-5 h-5 text-amber-500" />
                <h2 className="text-lg font-bold text-slate-900">
                  Verdict: Side {result.verdict} Wins!
                </h2>
                {result.run_id && (
                  <WhyButton onClick={() => setWhyRunId(result.run_id)} label="Why this verdict?" />
                )}
              </div>
              <p className="text-xs text-slate-600">
                Score: <span className="font-semibold text-emerald-700">{result.model_a} (FOR)</span> scored {result.score_a || '—'} vs <span className="font-semibold text-rose-700">{result.model_b} (AGAINST)</span> scored {result.score_b || '—'}
              </p>
            </div>

            <span className="text-xs text-purple-700 font-mono bg-white/80 border border-purple-200 px-3 py-1 rounded-xl shadow-xs">
              Judged by {result.judge_model} {result.judge_flagged ? '(flagged)' : ''}
            </span>
          </div>

          {/* Transcript turns */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider flex items-center space-x-2">
              <MessagesSquare className="w-4 h-4 text-indigo-600" />
              <span>Full Debate Transcript</span>
            </h3>

            <div className="space-y-4">
              {result.turns.map((turn: any, idx: number) => (
                <div
                  key={idx}
                  className={`p-5 rounded-2xl border text-xs space-y-2 shadow-xs ${
                    turn.side === 'FOR'
                      ? 'bg-emerald-50/60 border-emerald-200 text-slate-800 ml-0 mr-8 sm:mr-16'
                      : 'bg-rose-50/60 border-rose-200 text-slate-800 ml-8 sm:ml-16 mr-0'
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-slate-200/60 pb-2">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`font-bold px-2 py-0.5 rounded text-[10px] ${
                          turn.side === 'FOR'
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                            : 'bg-rose-100 text-rose-800 border border-rose-200'
                        }`}
                      >
                        Round {turn.round} • {turn.side}
                      </span>
                      <span className="font-mono text-slate-600 text-[11px] font-semibold">{turn.model}</span>
                    </div>
                    <span className="text-[10px] text-slate-500 font-mono">{turn.word_count} words (capped at 120)</span>
                  </div>
                  <p className="leading-relaxed text-slate-800 font-normal">{turn.content}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {whyRunId && (
        <WhyPanel
          kind="debate"
          id={whyRunId}
          onClose={() => setWhyRunId(null)}
        />
      )}
    </div>
  )
}
