import { useState } from 'react'

export default function SlingerDrafts({ drafts }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(null)

  if (!drafts) return null

  const { subject, emails = [], raw } = drafts

  function copy(text, key) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <div className="card overflow-hidden">
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
            {subject && (
              <div className="text-xs text-gray-500 mt-0.5">Subject: {subject}</div>
            )}
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
        <div className="border-t border-gray-100 p-5 space-y-4">
          {subject && (
            <div className="flex items-center justify-between p-3 bg-yotpo-pale rounded-lg border border-yotpo-border">
              <div>
                <div className="text-xs font-semibold text-yotpo-purple uppercase tracking-wide mb-0.5">Subject line (shared)</div>
                <div className="text-sm font-medium text-gray-900">{subject}</div>
              </div>
              <button
                onClick={() => copy(subject, 'subject')}
                className="ml-3 text-xs text-yotpo-purple hover:text-yotpo-light font-medium flex-shrink-0"
              >
                {copied === 'subject' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
          )}

          {emails.map(email => (
            <div key={email.num} className="border border-gray-100 rounded-lg overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-100">
                <span className="text-xs font-bold text-gray-600 uppercase tracking-wide">
                  Email {email.num}
                </span>
                <button
                  onClick={() => copy(email.body, `email-${email.num}`)}
                  className="text-xs text-yotpo-purple hover:text-yotpo-light font-medium"
                >
                  {copied === `email-${email.num}` ? '✓ Copied' : 'Copy'}
                </button>
              </div>
              <div className="px-4 py-3">
                <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap font-mono text-[13px]">
                  {email.body}
                </p>
              </div>
            </div>
          ))}

          {!emails.length && raw && (
            <div className="p-3 bg-gray-50 rounded-lg">
              <pre className="text-xs text-gray-600 whitespace-pre-wrap">{raw}</pre>
            </div>
          )}

          {emails.length > 0 && (
            <button
              onClick={() => copy(
                `Subject: ${subject}\n\n` + emails.map(e => `Email ${e.num}\n${e.body}`).join('\n\n'),
                'all'
              )}
              className="btn-secondary w-full justify-center text-xs"
            >
              {copied === 'all' ? '✓ Copied all' : 'Copy all emails'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
