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

  let barColor = 'bg-emerald-500'
  if (percent < 20) barColor = 'bg-rose-500'
  else if (percent < 50) barColor = 'bg-amber-500'

  return (
    <div className="w-full space-y-1">
      <div className="flex justify-between text-xs text-slate-300">
        <span>{label || 'Credits remaining'}</span>
        <span className="font-mono">
          {formatMicroUSD(remainingMicro)} / {formatMicroUSD(limitMicro)} ({percent}%)
        </span>
      </div>
      <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-300`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}
