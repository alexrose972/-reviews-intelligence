import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Nav from '../components/Nav.jsx'
import ScanProgress from '../components/ScanProgress.jsx'
import ScoreBar from '../components/ScoreBar.jsx'
import { GradeBadge, ScoreDisplay } from '../components/ScoreBadge.jsx'
import PitchAngles from '../components/PitchAngles.jsx'
import SlingerDrafts from '../components/SlingerDrafts.jsx'

export default function ScanResults() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [scan, setScan] = useState(null)
  const [events, setEvents] = useState([])
  const [status, setStatus] = useState('loading') // loading | running | complete | failed
  const [error, setError] = useState(null)
  const [expandedShot, setExpandedShot] = useState(null)
  const [rescanning, setRescanning] = useState(false)

  const wsRef = useRef(null)

  // Load initial scan state
  useEffect(() => {
    fetch(`/api/scans/${id}`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) throw new Error('Not found')
        return r.json()
      })
      .then(data => {
        setScan(data)
        setStatus(data.status)
      })
      .catch(() => setStatus('failed'))
  }, [id])

  // WebSocket for live updates
  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/scans/${id}`)
    wsRef.current = ws

    ws.onmessage = e => {
      const msg = JSON.parse(e.data)

      if (msg.type === 'progress') {
        setEvents(prev => [...prev, msg])
        setStatus('running')
      } else if (msg.type === 'complete') {
        setScan(msg.result)
        setStatus('complete')
      } else if (msg.type === 'error') {
        setError(msg.message)
        setStatus('failed')
      } else if (msg.type === 'already_complete' || msg.type === 'status') {
        setScan(msg.result)
        setStatus(msg.result?.status === 'failed' ? 'failed' : 'complete')
      }
    }

    ws.onerror = () => {
      // fall back to polling
      wsRef.current = null
    }

    return () => ws.close()
  }, [id])

  async function rescan() {
    if (!scan) return
    setRescanning(true)
    try {
      const r = await fetch('/api/scans', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: scan.domain,
          brand_name: scan.brand_name,
          account_owner: scan.account_owner || '',
          sf_reviews_provider: scan.sf_platform || null,
        }),
      })
      const data = await r.json()
      navigate(`/scan/${data.scan_id}`)
    } catch {
      setRescanning(false)
    }
  }

  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50">
        <Nav />
        <div className="flex items-center justify-center h-64">
          <div className="w-8 h-8 border-2 border-yotpo-purple border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Nav />

      <main className="max-w-5xl mx-auto px-4 py-8">
        {/* Header row */}
        <div className="flex items-start justify-between mb-6 gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-gray-400 mb-1">
              <button onClick={() => navigate('/')} className="hover:text-gray-600 transition-colors">
                Dashboard
              </button>
              <span>/</span>
              <span>{scan?.brand_name || id}</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">{scan?.brand_name || 'Scan Results'}</h1>
            {scan?.domain && <p className="text-sm text-gray-400 mt-0.5">{scan.domain}</p>}
          </div>

          {status === 'complete' && (
            <button
              onClick={rescan}
              disabled={rescanning}
              className="btn-secondary flex-shrink-0"
            >
              {rescanning ? 'Starting…' : 'Re-scan'}
            </button>
          )}
        </div>

        {/* ── Running state ── */}
        {(status === 'running' || (status === 'pending' && events.length === 0)) && (
          <div className="card p-6">
            <ScanProgress events={events} brandName={scan?.brand_name || ''} />
          </div>
        )}

        {/* ── Failed state ── */}
        {status === 'failed' && (
          <div className="card p-6 text-center">
            <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24">
                <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                  stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <p className="text-sm font-semibold text-gray-800 mb-1">Scan failed</p>
            <p className="text-xs text-gray-400">{error || scan?.error_message || 'An unexpected error occurred.'}</p>
            <button onClick={() => navigate('/')} className="btn-primary mt-4 text-sm">
              Back to Dashboard
            </button>
          </div>
        )}

        {/* ── Complete state ── */}
        {status === 'complete' && scan && (
          <div className="space-y-6">
            {/* Score hero */}
            <div className="card p-6">
              <div className="flex flex-col sm:flex-row sm:items-center gap-6">
                {/* Score ring */}
                <div className="flex items-center gap-4 flex-shrink-0">
                  <ScoreRing score={scan.overall_score} />
                  <div>
                    <div className="text-3xl font-black text-gray-900 tabular-nums">
                      {scan.overall_score}<span className="text-lg font-normal text-gray-400">/100</span>
                    </div>
                    <div className="mt-1">
                      <GradeBadge grade={scan.grade} size="lg" />
                    </div>
                    <p className="text-xs text-gray-400 mt-1">{gradeLabel(scan.grade)}</p>
                  </div>
                </div>

                {/* Divider */}
                <div className="sm:border-l border-gray-100 sm:pl-6 flex-1">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                    {scan.detected_platform && (
                      <MetaChip label="Detected platform" value={scan.detected_platform} />
                    )}
                    {scan.sf_platform && (
                      <MetaChip label="SF platform" value={scan.sf_platform} />
                    )}
                    {scan.platform_mismatch && (
                      <MetaChip label="Platform mismatch" value="⚠ Mismatch" warn />
                    )}
                    {scan.triggered_by && (
                      <MetaChip label="Scanned by" value={formatEmail(scan.triggered_by)} />
                    )}
                    {scan.triggered_at && (
                      <MetaChip label="Scanned" value={formatDate(scan.triggered_at)} />
                    )}
                  </div>
                </div>

                {/* PDF download */}
                <a
                  href={`/api/scans/${id}/pdf`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-secondary flex-shrink-0 text-sm"
                >
                  <svg width="16" height="16" fill="none" viewBox="0 0 16 16">
                    <path d="M8 2v8m0 0l-3-3m3 3l3-3M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  Download PDF Brief
                </a>
              </div>
            </div>

            {/* Pitch angles */}
            {scan.pitch_angles?.length > 0 && (
              <PitchAngles angles={scan.pitch_angles} />
            )}

            {/* Dimension breakdown */}
            <div className="card p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-5">Dimension Breakdown</h2>
              <ScoreBar scores={scan.scores || {}} />
            </div>

            {/* Recommendations */}
            {scan.recommendations?.length > 0 && (
              <div className="card p-6">
                <h2 className="text-base font-semibold text-gray-900 mb-4">Key Recommendations</h2>
                <div className="space-y-2">
                  {scan.recommendations.map((rec, i) => (
                    <div key={i} className="flex gap-3 text-sm text-gray-700">
                      <span className="text-yotpo-purple font-bold flex-shrink-0">{i + 1}.</span>
                      <span>{rec}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Screenshots */}
            {scan.screenshots?.length > 0 && (
              <div className="card p-6">
                <h2 className="text-base font-semibold text-gray-900 mb-4">Screenshots</h2>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {scan.screenshots.map((shot, i) => (
                    <button
                      key={i}
                      onClick={() => setExpandedShot(shot)}
                      className="rounded-lg overflow-hidden border border-gray-200 hover:border-yotpo-purple transition-colors group"
                    >
                      <img
                        src={`/api/scans/${id}/screenshot/${shot.label}`}
                        alt={shot.label}
                        className="w-full h-40 object-cover object-top group-hover:opacity-90 transition-opacity"
                      />
                      <div className="px-3 py-2 text-xs text-gray-500 font-medium bg-gray-50">
                        {formatShotLabel(shot.label)}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Slinger drafts */}
            {scan.slinger_drafts && (
              <SlingerDrafts drafts={scan.slinger_drafts} />
            )}
          </div>
        )}
      </main>

      {/* Screenshot lightbox */}
      {expandedShot && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
          onClick={() => setExpandedShot(null)}
        >
          <div className="relative max-w-4xl w-full" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setExpandedShot(null)}
              className="absolute -top-10 right-0 text-white/70 hover:text-white text-sm"
            >
              Close ✕
            </button>
            <img
              src={`/api/scans/${id}/screenshot/${expandedShot.label}`}
              alt={expandedShot.label}
              className="w-full rounded-xl shadow-2xl"
            />
            <div className="text-center text-white/60 text-xs mt-3">{formatShotLabel(expandedShot.label)}</div>
          </div>
        </div>
      )}
    </div>
  )
}

function ScoreRing({ score }) {
  const r = 36
  const circ = 2 * Math.PI * r
  const pct = Math.min(100, Math.max(0, score || 0))
  const offset = circ - (pct / 100) * circ
  const color = pct >= 80 ? '#22c55e' : pct >= 60 ? '#f97316' : pct >= 40 ? '#f59e0b' : '#ef4444'

  return (
    <svg width="96" height="96" viewBox="0 0 96 96">
      <circle cx="48" cy="48" r={r} fill="none" stroke="#f3f4f6" strokeWidth="8" />
      <circle
        cx="48" cy="48" r={r}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 48 48)"
        style={{ transition: 'stroke-dashoffset 1s ease' }}
      />
    </svg>
  )
}

function MetaChip({ label, value, warn }) {
  return (
    <div>
      <div className="text-xs text-gray-400 mb-0.5">{label}</div>
      <div className={`text-sm font-medium ${warn ? 'text-amber-600' : 'text-gray-800'}`}>{value}</div>
    </div>
  )
}

function gradeLabel(grade) {
  return {
    A: 'Excellent reviews experience',
    B: 'Good — some gaps to close',
    C: 'Average — clear opportunities',
    D: 'Below average — strong pitch',
    F: 'Poor — urgent case for Yotpo',
  }[grade] || ''
}

function formatEmail(email = '') {
  const name = email.split('@')[0]
  return name.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function formatDate(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatShotLabel(label = '') {
  return {
    homepage: 'Homepage',
    category: 'Category / Collections',
    bestsellers: 'Best Sellers',
  }[label] || label
}
