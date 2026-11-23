import React from 'react'
import { HelpCircle } from 'lucide-react'

interface WhyButtonProps {
  onClick: () => void
  label?: string
  className?: string
}

export const WhyButton: React.FC<WhyButtonProps> = ({
  onClick,
  label = 'Why?',
  className = '',
}) => {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={`inline-flex items-center space-x-1 px-2 py-0.5 text-xs font-medium text-emerald-400 bg-emerald-950/60 hover:bg-emerald-900/60 border border-emerald-800/60 rounded-full transition cursor-pointer ${className}`}
      title="View explanation and facts behind this decision or number"
    >
      <HelpCircle className="w-3 h-3" />
      <span>{label}</span>
    </button>
  )
}
