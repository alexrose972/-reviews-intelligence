import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Nav from '../components/Nav.jsx'
import { GradeBadge, ScoreDisplay } from '../components/ScoreBadge.jsx'
import { useAuth } from '../App.jsx'

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [sfAccounts, setSfAccounts] = useState([])
  const [query, setQuery] = useState('')
  const [filtered, setFiltered] = useState([])
  const [selected, setSelected] = useState(null)
  const [customDomain, setCustomDomain] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [recentScans, setRecentScans] = useState([])
  const [recentCheck, setRecentCheck] = useState(null)
  const [loadingRecent, setLoadingRecent] = useState(true)
  const inputRef = useRef()
  const dropdownRef = useRef()

  // Load SF accounts
  useEffect(() => {
    fetch('/api/sf-accounts', { credentials: 'include' })
      .then(r => r.json())
      .then(setSfAccounts)
      .catch(() => {})
  }, [])

  // Load recent scans
  useEffect(() => {
    setLoadingRecent(true)
    fetch('/api/scans?limit=10', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setRecentScans(data); setLoadingRecent(false) })
      .catch(() => setLoadingRecent(false))
  }, [])

  // Filter SF accounts as user types
  useEffect(() => {
    if (!query) { setFiltered(sfAccounts.slice(0, 8)); return }
    const q = query.toLowerCase()
    setFiltered(
      sfAccounts.filter(a =>
        a.name.toLowerCase().includes(q) || a.domain.toLowerCase().includes(q)
      ).slice(0, 8)
    )
  }, [query, sfAccounts])

  // Check if selected domain was scanned recently
  useEffect(() => {
    const domain = selected?.domain || customDomain.trim()
    if (!domain) { setRecentCheck(null); return }
    fetch(`/api/check-recent?domain=${encodeURIComponent(domain)}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => setRecentCheck(data.found ? data.scan : null))
      .catch(() => setRecentCheck(null))
  }, [selected, customDomain])

  // Close dropdown on outside click
  useEffect(() => {
    function handler(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function selectAccount(account) {
    setSelected(account)
    setQuery(account.name)
    setCustomDomain('')
    setShowDropdown(false)
  }

  async function runScan() {
    const domain = selected?.domain || customDomain.trim()
    const brandName = selected?.name || customDomain.trim()
    if (!domain) return

    setScanning(true)
    try {
      const r = await fetch('/api/scans', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain,
          brand_name: brandName,
          account_owner: selected?.account_owner || user?.name || '',
          sf_reviews_provider: selected?.sf_reviews_provider || null,
        }),
      })
      const data = await r.json()
      navigate(`/scan/${data.scan_id}`)
    } catch (e) {
      alert('Failed to start scan. Check the console for details.')
      setScanning(false)
    }
  }

  const activeDomain = selected?.domain || customDomain.trim()
  const activeName   = selected?.name   || customDomain.trim()

  return (
    <div className="min-h-screen bg-gray-50">
      <Nav />

      <main className="max-w-6xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Reviews Intelligence</h1>
          <p className="text-gray-500 mt-1">Score brand review experiences. Generate briefs. Draft outreach.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* ── Scan a Brand ─────────────────────────────────────────── */}
          <div className="card p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-5">Scan a Brand</h2>

            {/* Recent check banner */}
            {recentCheck && (
              <div className="mb-4 p-3 rounded-lg bg-amber-50 border border-amber-200">
                <p className="text-sm text-amber-800">
                  <strong>{activeName}</strong> was last scanned{' '}
                  {daysAgo(recentCheck.triggered_at)} by{' '}
                  {firstName(recentCheck.triggered_by)} —{' '}
                  Score: <strong>{recentCheck.overall_score}/100</strong>
                </p>
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={() => navigate(`/scan/${recentCheck.id}`)}
                    className="btn-secondary text-xs py-1 px-3"
                  >
                    View Results
                  </button>
                  <button
                    onClick={runScan}
                    disabled={scanning}
                    className="btn-primary text-xs py-1 px-3"
                  >
                    Re-scan
                  </button>
                </div>
              </div>
            )}

            {/* Brand search */}
            <div className="mb-4" ref={dropdownRef}>
              <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">
                Brand name
              </label>
              <div className="relative">
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={e => {
                    setQuery(e.target.value)
                    setSelected(null)
                    setShowDropdown(true)
                  }}
                  onFocus={() => setShowDropdown(true)}
                  placeholder="Search Tier 1 accounts…"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
                />
                {showDropdown && filtered.length > 0 && (
                  <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-20 max-h-56 overflow-y-auto">
                    {filtered.map(a => (
                      <button
                        key={a.domain}
                        onClick={() => selectAccount(a)}
                        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-yotpo-pale text-left text-sm transition-colors"
                      >
                        <span className="font-medium text-gray-900">{a.name}</span>
                        <span className="text-xs text-gray-400">{a.domain}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Or custom domain */}
            <div className="mb-5">
              <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">
                Or enter any domain
              </label>
              <input
                type="text"
                value={customDomain}
                onChange={e => { setCustomDomain(e.target.value); setSelected(null); setQuery('') }}
                placeholder="e.g. allbirds.com"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
              />
            </div>

            {/* Selected summary */}
            {selected && (
              <div className="mb-4 p-3 rounded-lg bg-yotpo-pale border border-yotpo-border">
                <div className="text-sm font-semibold text-yotpo-purple">{selected.name}</div>
                <div className="text-xs text-gray-500 mt-0.5 flex gap-3">
                  <span>{selected.domain}</span>
                  <span>AE: {selected.account_owner}</span>
                  {selected.sf_reviews_provider && <span>SF: {selected.sf_reviews_provider}</span>}
                </div>
              </div>
            )}

            <button
              onClick={runScan}
              disabled={!activeDomain || scanning}
              className="btn-primary w-full justify-center"
            >
              {scanning ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Starting scan…
                </>
              ) : (
                <>
                  <svg width="16" height="16" fill="none" viewBox="0 0 16 16">
                    <circle cx="6" cy="6" r="4" stroke="white" strokeWidth="1.5"/>
                    <path d="M10 10l3 3" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  Run Scan
                </>
              )}
            </button>
          </div>

          {/* ── Recent Scans ──────────────────────────────────────────── */}
          <div className="card p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-5">Recent Scans</h2>

            {loadingRecent ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : recentScans.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">No scans yet. Run your first scan!</p>
            ) : (
              <div className="space-y-1">
                {recentScans.map(scan => (
                  <button
                    key={scan.id}
                    onClick={() => navigate(`/scan/${scan.id}`)}
                    className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 text-left transition-colors group"
                  >
                    <StatusDot status={scan.status} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900 truncate">{scan.brand_name}</div>
                      <div className="text-xs text-gray-400">
                        {firstName(scan.triggered_by)} · {daysAgo(scan.triggered_at)}
                      </div>
                    </div>
                    {scan.overall_score != null && (
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <span className="text-sm font-bold text-gray-700 tabular-nums">
                          {scan.overall_score}
                        </span>
                        <GradeBadge grade={scan.grade} />
                      </div>
                    )}
                    <svg className="w-4 h-4 text-gray-300 group-hover:text-gray-500 flex-shrink-0 transition-colors" fill="none" viewBox="0 0 16 16">
                      <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </button>
                ))}
              </div>
            )}

            <div className="mt-4 pt-4 border-t border-gray-100">
              <button
                onClick={() => navigate('/history')}
                className="text-xs text-yotpo-purple font-medium hover:text-yotpo-light transition-colors"
              >
                View full history →
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

function StatusDot({ status }) {
  const cls = {
    complete: 'bg-green-400',
    running:  'bg-yotpo-purple animate-pulse',
    pending:  'bg-yellow-400',
    failed:   'bg-red-400',
  }[status] || 'bg-gray-300'
  return <div className={`w-2 h-2 rounded-full flex-shrink-0 ${cls}`} />
}

function daysAgo(ts) {
  if (!ts) return ''
  const diff = Date.now() - new Date(ts).getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return `${days}d ago`
}

function firstName(email = '') {
  const name = email.split('@')[0]
  return name.split('.')[0].charAt(0).toUpperCase() + name.split('.')[0].slice(1)
}
