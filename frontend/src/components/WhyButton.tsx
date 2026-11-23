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
      className={`inline-flex items-center space-x-1 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 bg-gradient-to-r from-indigo-50 to-violet-50 hover:from-indigo-100 hover:to-violet-100 border border-indigo-200/80 rounded-full transition shadow-xs cursor-pointer ${className}`}
      title="View explanation and facts behind this decision or number"
    >
      <HelpCircle className="w-3 h-3 text-indigo-600" />
      <span>{label}</span>
    </button>
  )
}
