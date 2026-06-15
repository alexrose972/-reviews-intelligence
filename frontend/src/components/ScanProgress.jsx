const STEPS = [
  { key: 'fetch',            label: 'Fetching website' },
  { key: 'llm_crawlability', label: 'LLM crawlability probe' },
  { key: 'review_richness',  label: 'Review richness analysis' },
  { key: 'review_recency',   label: 'Review recency check' },
  { key: 'visibility',       label: 'Visibility / discoverability' },
  { key: 'rich_snippets',    label: 'Rich snippets / schema' },
  { key: 'page_speed',       label: 'PageSpeed Insights' },
  { key: 'bestseller_depth', label: 'Bestseller review depth' },
  { key: 'stars_on_category','label': 'Stars on category pages' },
  { key: 'vertical_signals', label: 'Vertical signals' },
  { key: 'screenshots',      label: 'Screenshots' },
  { key: 'pdf',              label: 'Generating PDF brief' },
  { key: 'slinger',          label: 'Slinger 3000 email drafts' },
]

export default function ScanProgress({ events = [], brandName = '' }) {
  // Build step status map from events
  const statusMap = {}
  const detailMap = {}
  for (const evt of events) {
    if (evt.type === 'progress') {
      statusMap[evt.step] = evt.status
      if (evt.message) detailMap[evt.step] = evt.message
      if (evt.score !== undefined) detailMap[evt.step] = `Score: ${evt.score}/${evt.max_score}`
      if (evt.perf_score !== undefined) detailMap[evt.step] = `Mobile: ${evt.perf_score}/100`
      if (evt.count !== undefined) detailMap[evt.step] = `${evt.count} captured`
    }
  }

  const completedCount = Object.values(statusMap).filter(s => s === 'complete').length
  const totalSteps = STEPS.length
  const progressPct = Math.round((completedCount / totalSteps) * 100)

  return (
    <div className="space-y-5">
      {/* Brand + progress bar */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-gray-700">
            Scanning <span className="text-yotpo-purple">{brandName}</span>
          </h3>
          <span className="text-xs text-gray-400">{progressPct}%</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-yotpo-purple rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Step list */}
      <div className="space-y-1.5">
        {STEPS.map(step => {
          const status = statusMap[step.key]
          const detail = detailMap[step.key]

          return (
            <div key={step.key} className="flex items-center gap-3">
              {/* Icon */}
              <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
                {status === 'complete' ? (
                  <CheckIcon />
                ) : status === 'running' ? (
                  <Spinner />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-gray-200" />
                )}
              </div>

              {/* Label */}
              <span className={`text-sm ${
                status === 'complete' ? 'text-gray-700' :
                status === 'running'  ? 'text-yotpo-purple font-medium' :
                'text-gray-400'
              }`}>
                {step.label}
              </span>

              {/* Detail */}
              {detail && status !== 'running' && (
                <span className="text-xs text-gray-400 ml-auto">{detail}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function CheckIcon() {
  return (
    <svg className="w-5 h-5 text-green-500" fill="none" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="10" fill="currentColor" fillOpacity=".15"/>
      <path d="M6 10l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function Spinner() {
  return (
    <svg className="w-5 h-5 animate-spin text-yotpo-purple" fill="none" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeOpacity=".2" strokeWidth="2.5"/>
      <path d="M10 2a8 8 0 0 1 8 8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
    </svg>
  )
}
