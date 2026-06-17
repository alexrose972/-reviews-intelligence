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
  const [chromeStatus, setChromeStatus] = useState(null)
  const [triggeringChrome, setTriggeringChrome] = useState(false)

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

  // Poll Chrome status while job is running/queued
  useEffect(() => {
    if (!scan) return
    const mode = scan.scan_mode
    const jobStatus = scan.chrome_job_status
    if (!jobStatus || jobStatus === 'complete' || jobStatus === 'failed' || jobStatus === 'timeout') return

    function loadChromeStatus() {
      fetch(`/api/scans/${id}/chrome-status`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => {
          setChromeStatus(d)
          if (d.overall_status === 'complete') {
            clearInterval(poll)
            // Reload full scan
            fetch(`/api/scans/${id}`, { credentials: 'include' })
              .then(r => r.json())
              .then(data => { setScan(data); setStatus('complete') })
          }
        })
        .catch(() => {})
    }
    loadChromeStatus()
    const poll = setInterval(loadChromeStatus, 5000)
    return () => clearInterval(poll)
  }, [id, scan?.chrome_job_status])

  async function triggerChromeScan() {
    setTriggeringChrome(true)
    try {
      const r = await fetch(`/api/scans/${id}/chrome-fallback`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'manual' }),
      })
      const d = await r.json()
      // Reload scan to reflect new chrome_job_status
      const updated = await fetch(`/api/scans/${id}`, { credentials: 'include' }).then(r => r.json())
      setScan(updated)
    } catch {
      // ignore
    } finally {
      setTriggeringChrome(false)
    }
  }

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
      } else if (msg.type === 'blocked') {
        setError(msg.message)
        setStatus('blocked')
        // Refresh to pick up chrome_job_status / fallback reason for the banner
        fetch(`/api/scans/${id}`, { credentials: 'include' })
          .then(r => r.json())
          .then(data => setScan(data))
          .catch(() => {})
      } else if (msg.type === 'already_complete' || msg.type === 'status') {
        setScan(msg.result)
        setStatus(msg.result?.status || 'complete')
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

        {/* ── Chrome browser status banner ── */}
        {scan?.chrome_job_status && scan.chrome_job_status !== 'complete' && (
          <ChromeStatusBanner
            jobStatus={scan.chrome_job_status}
            brandName={scan.brand_name}
            fallbackReason={scan.scan_fallback_reason}
            chromeStatus={chromeStatus}
          />
        )}

        {/* ── Low-confidence manual Chrome trigger ── */}
        {status === 'complete' && scan && !scan.chrome_job_status && (
          <LowConfidencePrompt
            scan={scan}
            onRescan={rescan}
            rescanning={rescanning}
          />
        )}

        {/* ── Running state ── */}
        {(status === 'running' || (status === 'pending' && events.length === 0)) && (
          <div className="card p-6">
            <ScanProgress events={events} brandName={scan?.brand_name || ''} />
          </div>
        )}

        {/* ── Blocked state (bot protection — no score generated) ── */}
        {status === 'blocked' && (
          <BlockedCard
            scan={scan}
            error={error}
            chromeStatus={chromeStatus}
            onTrigger={triggerChromeScan}
            triggering={triggeringChrome}
            onRescan={rescan}
            rescanning={rescanning}
            onBack={() => navigate('/')}
          />
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
            <EvidencePanel evidence={scan.evidence} onTrigger={rescan} triggering={rescanning} />

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

// ── Chrome status banner ───────────────────────────────────────────────────────

function ChromeStatusBanner({ jobStatus, brandName, fallbackReason, chromeStatus }) {
  const runner = chromeStatus?.runner
  const runnerOffline = (jobStatus === 'queued' || jobStatus === 'running') && runner && !runner.online
  const statusLabel = {
    queued: 'Queued — waiting for Chrome runner',
    running: 'Chrome is auditing in real-time…',
    failed: 'Chrome scan failed',
    timeout: 'Chrome scan timed out',
  }[jobStatus] || jobStatus

  const reasonLabel = {
    no_pdps_found: 'Playwright found 0 product pages',
    no_reviews_extracted: 'Playwright found 0 reviews',
    bot_detection_suspected: 'Bot detection suspected',
    manual: 'Manual trigger',
  }[fallbackReason] || fallbackReason

  const isActive = jobStatus === 'queued' || jobStatus === 'running'

  return (
    <div className={`mb-6 p-4 rounded-xl border ${runnerOffline ? 'bg-amber-50 border-amber-200' : isActive ? 'bg-blue-50 border-blue-200' : 'bg-amber-50 border-amber-200'}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">🌐</span>
        <span className={`font-semibold text-sm ${runnerOffline ? 'text-amber-800' : isActive ? 'text-blue-800' : 'text-amber-800'}`}>
          Browser Scan Mode
        </span>
        {isActive && !runnerOffline && (
          <div className="w-3 h-3 rounded-full bg-blue-500 animate-pulse ml-1" />
        )}
      </div>
      <p className={`text-sm ${runnerOffline ? 'text-amber-700' : isActive ? 'text-blue-700' : 'text-amber-700'}`}>
        {statusLabel} — <span className="font-medium">{brandName}</span>
        {reasonLabel && <span className="text-xs ml-2 opacity-70">(reason: {reasonLabel})</span>}
      </p>
      {runnerOffline && (
        <p className="text-xs text-amber-700 mt-2">
          No Browser Scan runner is online. Start the local runner, then this job will be picked up automatically.
        </p>
      )}
      {runner?.online && (
        <p className="text-xs text-blue-600 mt-1">Runner online — last check {runner.seconds_since_seen}s ago.</p>
      )}
      {chromeStatus?.chrome_pdps_visited > 0 && (
        <p className="text-xs text-blue-600 mt-1">
          {chromeStatus.chrome_pdps_visited} product pages visited
        </p>
      )}
    </div>
  )
}

// ── Blocked state (bot protection blocked the scanner) ─────────────────────────

function BlockedCard({ scan, error, onRescan, rescanning, onBack }) {
  const message = error || scan?.error_message ||
    'This site is behind heavy bot protection and the scan couldn’t read it this time. Re-scanning usually gets through.'

  return (
    <div className="card p-6 text-center">
      <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-3">
        <span className="text-2xl">🛡️</span>
      </div>
      <p className="text-sm font-semibold text-gray-800 mb-1">
        Couldn’t reach the live site
      </p>
      <p className="text-xs text-gray-500 max-w-md mx-auto">{message}</p>

      <div className="flex items-center justify-center gap-2 mt-4">
        <button onClick={onRescan} disabled={rescanning} className="btn-primary text-sm py-1.5 px-4">
          {rescanning ? 'Re-scanning…' : 'Re-scan'}
        </button>
        <button onClick={onBack} className="btn-secondary text-sm py-1.5 px-4">
          Back to Dashboard
        </button>
      </div>
    </div>
  )
}

// ── Low-confidence manual Chrome trigger ───────────────────────────────────────

function LowConfidencePrompt({ scan, onRescan, rescanning }) {
  const scores = scan.scores || {}
  // Only count dimensions we actually MEASURED (exclude 'not measured' ones).
  const zeroCount = Object.entries(scores).filter(
    ([k, v]) => k !== 'llm_crawlability' && v?.measured !== false && (v?.score ?? 1) === 0
  ).length
  const isLowConfidence = (scan.overall_score ?? 100) < 30 && zeroCount >= 3

  if (!isLowConfidence) return null

  return (
    <div className="mb-6 p-4 rounded-xl border border-amber-200 bg-amber-50">
      <p className="text-sm font-semibold text-amber-800 mb-1">
        ⚠️ This scan may be incomplete
      </p>
      <p className="text-sm text-amber-700 mb-3">
        A low score with several areas at zero can mean the page didn’t fully load this time.
        Re-scan for a cleaner read.
      </p>
      <button
        onClick={onRescan}
        disabled={rescanning}
        className="btn-primary text-sm py-1.5 px-4"
      >
        {rescanning ? 'Re-scanning…' : 'Re-scan'}
      </button>
    </div>
  )
}

function EvidencePanel({ evidence, onTrigger, triggering }) {
  if (!evidence) return null

  const theme = {
    high: {
      wrap: 'border-green-200 bg-green-50',
      dot: 'bg-green-500',
      text: 'text-green-800',
      label: 'High confidence',
    },
    medium: {
      wrap: 'border-amber-200 bg-amber-50',
      dot: 'bg-amber-500',
      text: 'text-amber-800',
      label: 'Medium confidence',
    },
    low: {
      wrap: 'border-red-200 bg-red-50',
      dot: 'bg-red-500',
      text: 'text-red-800',
      label: 'Low confidence',
    },
    pending: {
      wrap: 'border-blue-200 bg-blue-50',
      dot: 'bg-blue-500',
      text: 'text-blue-800',
      label: 'Verification pending',
    },
    blocked: {
      wrap: 'border-amber-200 bg-amber-50',
      dot: 'bg-amber-500',
      text: 'text-amber-800',
      label: 'Blocked',
    },
  }[evidence.level] || {
    wrap: 'border-gray-200 bg-white',
    dot: 'bg-gray-400',
    text: 'text-gray-800',
    label: 'Evidence',
  }

  const shouldOfferBrowserScan = evidence.level === 'low' || evidence.level === 'blocked'

  return (
    <div className={`rounded-xl border p-4 ${theme.wrap}`}>
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${theme.dot}`} />
            <p className={`text-sm font-semibold ${theme.text}`}>{theme.label}</p>
          </div>
          <p className={`text-sm mt-1 leading-relaxed ${theme.text}`}>{evidence.summary}</p>
          {evidence.next_action && (
            <p className="text-xs text-gray-600 mt-2">{evidence.next_action}</p>
          )}
        </div>
        <div className={`text-2xl font-black tabular-nums leading-none ${theme.text}`}>
          {evidence.score}<span className="text-sm font-semibold opacity-60">/100</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <EvidenceList title="Proof found" items={evidence.proof} empty="No proof captured yet." />
        <EvidenceList title="Gaps to verify" items={evidence.gaps} empty="No major evidence gaps." />
      </div>

      {shouldOfferBrowserScan && (
        <button
          onClick={onTrigger}
          disabled={triggering}
          className="btn-primary text-sm py-1.5 px-4 mt-4"
        >
          {triggering ? 'Re-scanning...' : 'Re-scan'}
        </button>
      )}
    </div>
  )
}

function EvidenceList({ title, items = [], empty }) {
  return (
    <div className="rounded-lg bg-white/70 border border-white/80 p-3">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</p>
      {items.length > 0 ? (
        <div className="space-y-1.5">
          {items.map(item => (
            <div key={item} className="flex items-start gap-2 text-xs text-gray-700">
              <span className="mt-1 w-1.5 h-1.5 rounded-full bg-gray-400 flex-shrink-0" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-400">{empty}</p>
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
