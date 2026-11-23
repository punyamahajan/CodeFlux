import React from 'react'
import { formatMicroUSD } from '../utils'

interface UsageBarProps {
  remainingMicro: number
  limitMicro: number
  label?: string
}

export const UsageBar: React.FC<UsageBarProps> = ({ remainingMicro, limitMicro, label }) => {
  const safeLimit = Math.max(1, limitMicro)
  const percent = Math.min(100, Math.max(0, Math.round((remainingMicro / safeLimit) * 100)))

  let barColor = 'bg-gradient-to-r from-emerald-500 to-teal-500'
  if (percent < 20) barColor = 'bg-rose-500'
  else if (percent < 50) barColor = 'bg-amber-500'

  return (
    <div className="w-full space-y-1.5">
      <div className="flex justify-between text-xs text-slate-600 font-medium">
        <span>{label || 'Credits remaining'}</span>
        <span className="font-mono font-semibold text-slate-800">
          {formatMicroUSD(remainingMicro)} / {formatMicroUSD(limitMicro)} ({percent}%)
        </span>
      </div>
      <div className="h-2 w-full bg-slate-100 border border-slate-200/60 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-300 rounded-full`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}
