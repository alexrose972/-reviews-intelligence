const COLORS = {
  A: 'bg-green-100 text-green-800 border-green-200',
  B: 'bg-orange-100 text-orange-800 border-orange-200',
  C: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  D: 'bg-red-100 text-red-800 border-red-200',
}

const BIG_COLORS = {
  A: 'text-green-600',
  B: 'text-orange-500',
  C: 'text-yellow-500',
  D: 'text-red-600',
}

export function GradeBadge({ grade, size = 'sm' }) {
  const cls = COLORS[grade] || 'bg-gray-100 text-gray-600 border-gray-200'
  if (size === 'lg') {
    return (
      <span className={`inline-flex items-center justify-center w-12 h-12 rounded-full border-2 text-xl font-black ${cls}`}>
        {grade}
      </span>
    )
  }
  return (
    <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full border text-xs font-black ${cls}`}>
      {grade}
    </span>
  )
}

export function ScoreDisplay({ score, grade, size = 'md' }) {
  const color = BIG_COLORS[grade] || 'text-gray-600'
  if (size === 'xl') {
    return (
      <div className="flex items-end gap-2">
        <span className={`text-6xl font-black tabular-nums ${color}`}>{score}</span>
        <span className="text-2xl text-gray-400 font-light mb-2">/100</span>
      </div>
    )
  }
  return (
    <span className={`text-2xl font-black tabular-nums ${color}`}>
      {score}<span className="text-sm text-gray-400 font-normal">/100</span>
    </span>
  )
}
