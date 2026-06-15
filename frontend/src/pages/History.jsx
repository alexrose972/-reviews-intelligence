import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Nav from '../components/Nav.jsx'
import { GradeBadge } from '../components/ScoreBadge.jsx'

const SORT_OPTIONS = [
  { value: 'triggered_at_desc', label: 'Newest first' },
  { value: 'triggered_at_asc',  label: 'Oldest first' },
  { value: 'score_desc',        label: 'Highest score' },
  { value: 'score_asc',         label: 'Lowest score' },
  { value: 'brand_asc',         label: 'Brand A–Z' },
]

export default function History() {
  const navigate = useNavigate()

  const [scans, setScans] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState('triggered_at_desc')
  const [statusFilter, setStatusFilter] = useState('all')
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetch('/api/scans?limit=200', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setScans(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  // Filter
  const filtered = scans
    .filter(s => {
      if (statusFilter !== 'all' && s.status !== statusFilter) return false
      if (query) {
        const q = query.toLowerCase()
        return s.brand_name?.toLowerCase().includes(q) || s.domain?.toLowerCase().includes(q)
      }
      return true
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'triggered_at_desc': return new Date(b.triggered_at) - new Date(a.triggered_at)
        case 'triggered_at_asc':  return new Date(a.triggered_at) - new Date(b.triggered_at)
        case 'score_desc': return (b.overall_score ?? -1) - (a.overall_score ?? -1)
        case 'score_asc':  return (a.overall_score ?? 101) - (b.overall_score ?? 101)
        case 'brand_asc':  return (a.brand_name || '').localeCompare(b.brand_name || '')
        default: return 0
      }
    })

  async function exportExcel() {
    setExporting(true)
    try {
      const r = await fetch('/api/history/export', { credentials: 'include' })
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `reviews-history-${todayStr()}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Nav />

      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* Page header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Scan History</h1>
            <p className="text-gray-500 text-sm mt-0.5">
              {loading ? '…' : `${scans.length} total scans`}
            </p>
          </div>
          <button
            onClick={exportExcel}
            disabled={exporting || scans.length === 0}
            className="btn-secondary text-sm"
          >
            <svg width="15" height="15" fill="none" viewBox="0 0 15 15">
              <path d="M7.5 1v9m0 0L4 6.5m3.5 3.5L11 6.5M2 13h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {exporting ? 'Exporting…' : 'Export Excel'}
          </button>
        </div>

        {/* Filters */}
        <div className="card p-4 mb-6">
          <div className="flex flex-col sm:flex-row gap-3">
            {/* Search */}
            <div className="flex-1">
              <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search brand or domain…"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
              />
            </div>

            {/* Status filter */}
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="px-3 py-2 rounded-lg border border-gray-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
            >
              <option value="all">All statuses</option>
              <option value="complete">Complete</option>
              <option value="running">Running</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
            </select>

            {/* Sort */}
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value)}
              className="px-3 py-2 rounded-lg border border-gray-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="card overflow-hidden">
          {loading ? (
            <div className="p-8 space-y-3">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-12 text-center text-sm text-gray-400">
              {query || statusFilter !== 'all' ? 'No scans match your filters.' : 'No scans yet. Run your first scan!'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Brand</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">Domain</th>
                    <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Score</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Platform</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">Scanned by</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                    <th className="px-4 py-3 w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {filtered.map(scan => (
                    <tr
                      key={scan.id}
                      onClick={() => navigate(`/scan/${scan.id}`)}
                      className="hover:bg-gray-50 cursor-pointer transition-colors group"
                    >
                      <td className="px-4 py-3 font-medium text-gray-900">{scan.brand_name}</td>
                      <td className="px-4 py-3 text-gray-400 hidden sm:table-cell text-xs">{scan.domain}</td>
                      <td className="px-4 py-3 text-center">
                        {scan.overall_score != null ? (
                          <div className="flex items-center justify-center gap-1.5">
                            <span className="font-bold text-gray-800 tabular-nums">{scan.overall_score}</span>
                            {scan.grade && <GradeBadge grade={scan.grade} />}
                          </div>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 hidden md:table-cell text-xs">
                        {scan.detected_platform || '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-400 hidden lg:table-cell text-xs">
                        {formatEmail(scan.triggered_by)}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                        {formatDate(scan.triggered_at)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill status={scan.status} />
                      </td>
                      <td className="px-4 py-3">
                        <svg className="w-4 h-4 text-gray-300 group-hover:text-gray-500 transition-colors" fill="none" viewBox="0 0 16 16">
                          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {filtered.length > 0 && (
          <p className="text-xs text-gray-400 text-center mt-4">
            Showing {filtered.length} of {scans.length} scans
          </p>
        )}
      </main>
    </div>
  )
}

function StatusPill({ status }) {
  const styles = {
    complete: 'bg-green-100 text-green-700',
    running:  'bg-yotpo-pale text-yotpo-purple',
    pending:  'bg-yellow-100 text-yellow-700',
    failed:   'bg-red-100 text-red-600',
  }
  const labels = {
    complete: 'Complete',
    running:  'Running',
    pending:  'Pending',
    failed:   'Failed',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${styles[status] || 'bg-gray-100 text-gray-500'}`}>
      {labels[status] || status}
    </span>
  )
}

function formatEmail(email = '') {
  if (!email) return '—'
  const name = email.split('@')[0]
  return name.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}
