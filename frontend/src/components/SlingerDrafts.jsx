import { useState, useEffect } from 'react'

export default function SlingerDrafts({ drafts, scanId }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(null)

  // Send panel state
  const [sendOpen, setSendOpen] = useState(false)
  const [contacts, setContacts] = useState(null)
  const [loadingContacts, setLoadingContacts] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [variantIdx, setVariantIdx] = useState(0)
  const [editedSubject, setEditedSubject] = useState('')
  const [editedBody, setEditedBody] = useState('')
  const [sending, setSending] = useState(false)
  const [sendResults, setSendResults] = useState(null)
  const [gmailConnected, setGmailConnected] = useState(null)

  if (!drafts) return null

  const { subject, emails = [], raw } = drafts
  const currentEmail = emails[variantIdx]

  // Check gmail status + load contacts when send panel opens
  useEffect(() => {
    if (!sendOpen || contacts !== null) return
    setLoadingContacts(true)

    Promise.all([
      fetch('/api/me', { credentials: 'include' }).then(r => r.json()),
      fetch(`/api/scans/${scanId}/contacts`, { credentials: 'include' }).then(r => r.json()),
    ]).then(([me, contactData]) => {
      setGmailConnected(me.gmail_connected || false)
      setContacts(contactData.contacts || [])
      setLoadingContacts(false)
    }).catch(() => {
      setLoadingContacts(false)
      setContacts([])
    })
  }, [sendOpen, scanId])

  // Sync editable fields when variant changes
  useEffect(() => {
    if (!sendOpen) return
    setEditedSubject(subject || '')
    setEditedBody(currentEmail?.body || '')
  }, [variantIdx, sendOpen])

  // Check for ?gmail=connected in URL (returned after OAuth)
  useEffect(() => {
    if (window.location.search.includes('gmail=connected')) {
      setGmailConnected(true)
      setSendOpen(true)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  function copy(text, key) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  function toggleContact(email) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(email) ? next.delete(email) : next.add(email)
      return next
    })
  }

  function toggleAll() {
    if (!contacts) return
    if (selected.size === contacts.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(contacts.map(c => c.email)))
    }
  }

  async function handleSend() {
    if (!selected.size) return
    setSending(true)
    setSendResults(null)

    const selectedContacts = (contacts || []).filter(c => selected.has(c.email))

    try {
      const r = await fetch(`/api/scans/${scanId}/send-emails`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contacts: selectedContacts,
          subject: editedSubject,
          body: editedBody,
        }),
      })
      const data = await r.json()
      setSendResults(data)
    } catch {
      setSendResults({ sent: 0, failed: selected.size, results: [] })
    } finally {
      setSending(false)
    }
  }

  function connectGmail() {
    const returnTo = window.location.pathname
    window.location.href = `/auth/gmail?return_to=${encodeURIComponent(returnTo)}`
  }

  return (
    <div className="card overflow-hidden">
      {/* ── Header ── */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between p-5 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-yotpo-purple flex items-center justify-center">
            <svg width="16" height="16" fill="none" viewBox="0 0 16 16">
              <path d="M3 4h10M3 7h7M3 10h5" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </div>
          <div className="text-left">
            <div className="text-sm font-semibold text-gray-900">Slinger 3000 — Email Drafts</div>
            {subject && <div className="text-xs text-gray-500 mt-0.5">Subject: {subject}</div>}
          </div>
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 20 20"
        >
          <path d="M5 8l5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {open && (
        <div className="border-t border-gray-100">
          {/* ── Email drafts ── */}
          <div className="p-5 space-y-4">
            {subject && (
              <div className="flex items-center justify-between p-3 bg-yotpo-pale rounded-lg border border-yotpo-border">
                <div>
                  <div className="text-xs font-semibold text-yotpo-purple uppercase tracking-wide mb-0.5">Subject line (shared)</div>
                  <div className="text-sm font-medium text-gray-900">{subject}</div>
                </div>
                <button onClick={() => copy(subject, 'subject')} className="ml-3 text-xs text-yotpo-purple hover:text-yotpo-light font-medium flex-shrink-0">
                  {copied === 'subject' ? '✓ Copied' : 'Copy'}
                </button>
              </div>
            )}

            {emails.map(email => (
              <div key={email.num} className="border border-gray-100 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-100">
                  <span className="text-xs font-bold text-gray-600 uppercase tracking-wide">Email {email.num}</span>
                  <button onClick={() => copy(email.body, `email-${email.num}`)} className="text-xs text-yotpo-purple hover:text-yotpo-light font-medium">
                    {copied === `email-${email.num}` ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
                <div className="px-4 py-3">
                  <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap font-mono text-[13px]">{email.body}</p>
                </div>
              </div>
            ))}

            {!emails.length && raw && (
              <div className="p-3 bg-gray-50 rounded-lg">
                <pre className="text-xs text-gray-600 whitespace-pre-wrap">{raw}</pre>
              </div>
            )}

            <div className="flex gap-2">
              {emails.length > 0 && (
                <button
                  onClick={() => copy(`Subject: ${subject}\n\n` + emails.map(e => `Email ${e.num}\n${e.body}`).join('\n\n'), 'all')}
                  className="btn-secondary flex-1 justify-center text-xs"
                >
                  {copied === 'all' ? '✓ Copied all' : 'Copy all emails'}
                </button>
              )}
              {scanId && emails.length > 0 && (
                <button
                  onClick={() => { setSendOpen(o => !o); if (!sendOpen) { setEditedSubject(subject || ''); setEditedBody(currentEmail?.body || '') } }}
                  className="btn-primary flex-1 justify-center text-xs"
                >
                  <svg width="14" height="14" fill="none" viewBox="0 0 16 16">
                    <path d="M2 8l12-6-5 6 5 6-12-6z" stroke="white" strokeWidth="1.5" strokeLinejoin="round"/>
                  </svg>
                  {sendOpen ? 'Hide send panel' : 'Send via Gmail'}
                </button>
              )}
            </div>
          </div>

          {/* ── Send panel ── */}
          {sendOpen && (
            <div className="border-t border-gray-100 bg-gray-50 p-5 space-y-5">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-blue-100 flex items-center justify-center">
                  <svg width="12" height="12" fill="none" viewBox="0 0 16 16">
                    <path d="M2 8l12-6-5 6 5 6-12-6z" stroke="#3b82f6" strokeWidth="1.5" strokeLinejoin="round"/>
                  </svg>
                </div>
                <span className="text-sm font-semibold text-gray-900">Send via Gmail</span>
              </div>

              {/* Gmail not connected */}
              {gmailConnected === false && (
                <div className="p-4 rounded-lg border border-amber-200 bg-amber-50">
                  <p className="text-sm text-amber-800 mb-3">
                    Connect your Google account to send emails directly from your Gmail inbox.
                  </p>
                  <button onClick={connectGmail} className="btn-primary text-xs">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                    Connect Google Account
                  </button>
                </div>
              )}

              {gmailConnected && (
                <>
                  {/* Step 1 — Choose variant */}
                  {emails.length > 1 && (
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Choose email variant</label>
                      <div className="flex gap-2">
                        {emails.map((e, i) => (
                          <button
                            key={i}
                            onClick={() => { setVariantIdx(i); setEditedBody(e.body) }}
                            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${variantIdx === i ? 'bg-yotpo-purple text-white border-yotpo-purple' : 'bg-white text-gray-600 border-gray-200 hover:border-yotpo-purple'}`}
                          >
                            Email {e.num}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Step 2 — Contacts */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Select recipients</label>
                      {contacts && contacts.length > 0 && (
                        <button onClick={toggleAll} className="text-xs text-yotpo-purple hover:text-yotpo-light font-medium">
                          {selected.size === contacts.length ? 'Deselect all' : `Select all (${contacts.length})`}
                        </button>
                      )}
                    </div>

                    {loadingContacts && (
                      <div className="space-y-2">
                        {[...Array(3)].map((_, i) => <div key={i} className="h-10 bg-gray-200 rounded-lg animate-pulse" />)}
                      </div>
                    )}

                    {!loadingContacts && contacts && contacts.length === 0 && (
                      <p className="text-sm text-gray-400 text-center py-4">No contacts found in Salesforce for this brand.</p>
                    )}

                    {!loadingContacts && contacts && contacts.length > 0 && (
                      <div className="max-h-48 overflow-y-auto rounded-lg border border-gray-200 bg-white divide-y divide-gray-50">
                        {contacts.map(c => (
                          <label
                            key={c.email}
                            className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-yotpo-pale transition-colors ${selected.has(c.email) ? 'bg-yotpo-pale/50' : ''}`}
                          >
                            <input
                              type="checkbox"
                              checked={selected.has(c.email)}
                              onChange={() => toggleContact(c.email)}
                              className="rounded border-gray-300 text-yotpo-purple focus:ring-yotpo-purple/30 flex-shrink-0"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-medium text-gray-900 truncate">
                                {c.first_name} {c.last_name}
                              </div>
                              <div className="text-xs text-gray-400 truncate">{c.title} · {c.email}</div>
                            </div>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Step 3 — Edit subject + body */}
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">Subject</label>
                      <input
                        type="text"
                        value={editedSubject}
                        onChange={e => setEditedSubject(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple"
                      />
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Email body</label>
                        <span className="text-xs text-gray-400">Use {'{{first_name}}'} for personalization</span>
                      </div>
                      <textarea
                        value={editedBody}
                        onChange={e => setEditedBody(e.target.value)}
                        rows={10}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-yotpo-purple/30 focus:border-yotpo-purple resize-y"
                      />
                    </div>
                  </div>

                  {/* Step 4 — Send */}
                  <div>
                    <button
                      onClick={handleSend}
                      disabled={sending || !selected.size || !editedBody.trim()}
                      className="btn-primary w-full justify-center"
                    >
                      {sending ? (
                        <>
                          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          Sending…
                        </>
                      ) : (
                        <>
                          <svg width="14" height="14" fill="none" viewBox="0 0 16 16">
                            <path d="M2 8l12-6-5 6 5 6-12-6z" stroke="white" strokeWidth="1.5" strokeLinejoin="round"/>
                          </svg>
                          {selected.size ? `Send to ${selected.size} contact${selected.size > 1 ? 's' : ''}` : 'Select contacts to send'}
                        </>
                      )}
                    </button>

                    {/* Send results */}
                    {sendResults && (
                      <div className="mt-4 space-y-2">
                        <div className={`flex items-center gap-2 text-sm font-medium ${sendResults.failed === 0 ? 'text-green-700' : 'text-amber-700'}`}>
                          {sendResults.failed === 0 ? (
                            <>✓ All {sendResults.sent} emails sent successfully</>
                          ) : (
                            <>{sendResults.sent} sent, {sendResults.failed} failed</>
                          )}
                        </div>
                        <div className="rounded-lg border border-gray-200 bg-white divide-y divide-gray-50 max-h-36 overflow-y-auto">
                          {sendResults.results.map((r, i) => (
                            <div key={i} className="flex items-center gap-2 px-3 py-2">
                              <span className={`text-xs font-medium flex-shrink-0 ${r.ok ? 'text-green-600' : 'text-red-500'}`}>
                                {r.ok ? '✓' : '✗'}
                              </span>
                              <span className="text-xs text-gray-700 truncate">{r.name || r.email}</span>
                              {!r.ok && <span className="text-xs text-red-400 truncate ml-auto">{r.error}</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {gmailConnected === null && loadingContacts && (
                <div className="h-8 bg-gray-200 rounded animate-pulse" />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
