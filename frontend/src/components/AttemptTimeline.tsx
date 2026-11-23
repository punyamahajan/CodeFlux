import React from 'react'
import { CheckCircle2, XCircle, SkipForward } from 'lucide-react'

interface Attempt {
  provider: string
  model: string
  status_code?: number | null
  latency_ms?: number | null
  error?: string | null
  skipped?: boolean
  skip_reason?: string | null
}

interface AttemptTimelineProps {
  attempts: Attempt[]
}

export const AttemptTimeline: React.FC<AttemptTimelineProps> = ({ attempts }) => {
  if (!attempts || attempts.length === 0) {
    return <p className="text-xs text-slate-500 italic">No attempt records logged.</p>
  }

  return (
    <div className="space-y-3">
      {attempts.map((att, idx) => {
        const isSuccess = !att.skipped && !att.error && (!att.status_code || att.status_code < 400)
        const isSkipped = att.skipped
        const isFailed = !att.skipped && (Boolean(att.error) || (att.status_code && att.status_code >= 400))

        return (
          <div
            key={idx}
            className={`p-3 rounded-xl border flex items-start justify-between text-xs transition ${
              isSuccess
                ? 'bg-emerald-50/70 border-emerald-200 text-emerald-900'
                : isSkipped
                ? 'bg-slate-50 border-slate-200 text-slate-600'
                : 'bg-rose-50/70 border-rose-200 text-rose-900'
            }`}
          >
            <div className="flex items-start space-x-2.5">
              <div className="mt-0.5">
                {isSuccess && <CheckCircle2 className="w-4 h-4 text-emerald-600" />}
                {isSkipped && <SkipForward className="w-4 h-4 text-slate-400" />}
                {isFailed && <XCircle className="w-4 h-4 text-rose-600" />}
              </div>
              <div>
                <div className="font-semibold text-slate-900 flex items-center space-x-2">
                  <span>{att.provider} / {att.model}</span>
                  {att.status_code && (
                    <span className="px-1.5 py-0.5 bg-slate-100 border border-slate-200 rounded font-mono text-[10px] text-slate-700">
                      HTTP {att.status_code}
                    </span>
                  )}
                </div>
                {att.skip_reason && (
                  <p className="text-[11px] text-slate-500 mt-0.5">Skipped: {att.skip_reason}</p>
                )}
                {att.error && (
                  <p className="text-[11px] text-rose-700 mt-0.5 font-medium">Error: {att.error}</p>
                )}
              </div>
            </div>

            {att.latency_ms !== null && att.latency_ms !== undefined && (
              <span className="font-mono text-[11px] text-slate-500 font-medium">
                {att.latency_ms} ms
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
