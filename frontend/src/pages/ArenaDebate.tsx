import React, { useState } from 'react'
import { api } from '../api'
import { Swords, Play, AlertCircle, Award, MessagesSquare } from 'lucide-react'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const ArenaDebate: React.FC = () => {
  const [topic, setTopic] = useState('Should AI code generators be required to attribute their training data sources?')
  const [modelA, setModelA] = useState('gpt-4o-mini')
  const [modelB, setModelB] = useState('claude-3-haiku')
  const [judgeModel, setJudgeModel] = useState('gpt-4o-mini')
  const [rounds, setRounds] = useState(2)

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
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Swords className="w-6 h-6 text-purple-400" />
            <span>Debate Arena</span>
          </h1>
          <p className="text-xs text-slate-400">
            Oxford-style AI debates. Two models take opposing sides across structured rounds with a 120-word turn cap and AI judging.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Debate Setup Controls */}
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-2xl space-y-5 shadow-xl">
        <div>
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block mb-1.5">
            Debate Motion / Topic
          </label>
          <input
            type="text"
            required
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Is open source AI safer than proprietary AI?"
            className="w-full px-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white focus:outline-none focus:border-purple-500"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div>
            <label className="text-xs font-semibold text-emerald-400 uppercase tracking-wider block mb-1">
              Side FOR (Proponent)
            </label>
            <input
              type="text"
              value={modelA}
              onChange={(e) => setModelA(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-emerald-400 focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-rose-400 uppercase tracking-wider block mb-1">
              Side AGAINST (Opponent)
            </label>
            <input
              type="text"
              value={modelB}
              onChange={(e) => setModelB(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-rose-400 focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-purple-400 uppercase tracking-wider block mb-1">
              Judge Model
            </label>
            <input
              type="text"
              value={judgeModel}
              onChange={(e) => setJudgeModel(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-purple-400 focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block mb-1">
              Rounds (max 3)
            </label>
            <select
              value={rounds}
              onChange={(e) => setRounds(parseInt(e.target.value, 10))}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white focus:outline-none"
            >
              <option value={1}>1 Round</option>
              <option value={2}>2 Rounds (Default)</option>
              <option value={3}>3 Rounds (Full Debate)</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            onClick={handleRun}
            disabled={loading}
            className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-2 shadow-lg shadow-purple-600/20 transition disabled:opacity-50 cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{loading ? 'Running Multi-Round Debate...' : 'Start Oxford Debate'}</span>
          </button>
        </div>
      </div>

      {/* Results view */}
      {result && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 bg-slate-900 border border-purple-800/40 rounded-2xl shadow-xl">
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <Award className="w-5 h-5 text-amber-400" />
                <h2 className="text-lg font-bold text-white">
                  Verdict: Side {result.verdict} Wins!
                </h2>
                {result.run_id && (
                  <WhyButton onClick={() => setWhyRunId(result.run_id)} label="Why this verdict?" />
                )}
              </div>
              <p className="text-xs text-slate-300">
                Score: {result.model_a} (FOR) scored {result.score_a || '—'} vs {result.model_b} (AGAINST) scored {result.score_b || '—'}
              </p>
            </div>

            <span className="text-xs text-slate-400 font-mono">
              Judged by {result.judge_model} {result.judge_flagged ? '(flagged)' : ''}
            </span>
          </div>

          {/* Transcript turns */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center space-x-2">
              <MessagesSquare className="w-4 h-4 text-emerald-400" />
              <span>Full Debate Transcript</span>
            </h3>

            <div className="space-y-4">
              {result.turns.map((turn: any, idx: number) => (
                <div
                  key={idx}
                  className={`p-5 rounded-2xl border text-xs space-y-2 ${
                    turn.side === 'FOR'
                      ? 'bg-emerald-950/20 border-emerald-800/40 text-slate-200 ml-0 mr-8 sm:mr-16'
                      : 'bg-rose-950/20 border-rose-800/40 text-slate-200 ml-8 sm:ml-16 mr-0'
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-slate-800/60 pb-2">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`font-bold px-2 py-0.5 rounded text-[10px] ${
                          turn.side === 'FOR'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-rose-500/20 text-rose-400'
                        }`}
                      >
                        Round {turn.round} • {turn.side}
                      </span>
                      <span className="font-mono text-slate-400 text-[11px]">{turn.model}</span>
                    </div>
                    <span className="text-[10px] text-slate-500 font-mono">{turn.word_count} words (capped at 120)</span>
                  </div>
                  <p className="leading-relaxed text-slate-100">{turn.content}</p>
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
