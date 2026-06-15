const DIMENSION_LABELS = {
  llm_crawlability:  'LLM Crawlability',
  review_richness:   'Review Richness',
  review_recency:    'Review Recency',
  visibility:        'Visibility / Discoverability',
  rich_snippets:     'Rich Snippets',
  page_speed:        'Page Speed',
  bestseller_depth:  'Bestseller Depth',
  stars_on_category: 'Stars on Category Pages',
  vertical_signals:  'Vertical Signals',
}

const WHY_IT_MATTERS = {
  llm_crawlability:  "AI assistants can't recommend products they can't read.",
  review_richness:   'Shoppers need 40+ words to trust a purchase decision.',
  review_recency:    "60% of shoppers won't buy if the newest review is 3+ months old.",
  visibility:        'Stars above the fold reduce bounce rate.',
  rich_snippets:     'AggregateRating schema = star ratings in Google search results.',
  page_speed:        'Every 100ms of delay costs ~1% in mobile conversions.',
  bestseller_depth:  'Top products need 50+ reviews to rank and convert.',
  stars_on_category: 'Star ratings on collections lift PDP click-through ~30%.',
  vertical_signals:  'Fit and ingredient language in reviews drives category-specific lifts.',
}

const SCORE_WEIGHTS = {
  llm_crawlability: 20, review_richness: 18, review_recency: 15,
  visibility: 12, rich_snippets: 10, page_speed: 10,
  bestseller_depth: 8, stars_on_category: 4, vertical_signals: 3,
}

const DIM_ORDER = Object.keys(SCORE_WEIGHTS)

function barColor(pct) {
  if (pct >= 70) return 'bg-green-500'
  if (pct >= 40) return 'bg-orange-400'
  return 'bg-red-500'
}

export default function ScoreBar({ scores = {} }) {
  return (
    <div className="space-y-3">
      {DIM_ORDER.map(key => {
        const dim = scores[key] || {}
        const score = dim.score ?? 0
        const max = dim.max_score ?? SCORE_WEIGHTS[key] ?? 1
        const pct = Math.round((score / max) * 100)
        const label = DIMENSION_LABELS[key]
        const why = WHY_IT_MATTERS[key]
        const finding = dim.finding || ''

        return (
          <div key={key} className="grid grid-cols-[180px_1fr] gap-4 items-start">
            {/* Label + weight */}
            <div>
              <div className="text-sm font-semibold text-gray-800 flex items-center justify-between">
                <span>{label}</span>
                <span className="text-xs font-normal text-gray-400">{max}pts</span>
              </div>
              <div className="text-xs text-gray-400 mt-0.5 leading-tight">{why}</div>
            </div>

            {/* Bar + finding */}
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${barColor(pct)}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs font-semibold text-gray-600 w-12 text-right tabular-nums">
                  {score}/{max}
                </span>
              </div>
              {finding && (
                <p className="text-xs text-gray-500 leading-relaxed">{finding}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
