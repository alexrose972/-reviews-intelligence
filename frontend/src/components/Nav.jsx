import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../App.jsx'

export default function Nav() {
  const { user, logout } = useAuth()
  const loc = useLocation()

  const links = [
    { to: '/',        label: 'Scan' },
    { to: '/history', label: 'History' },
  ]

  return (
    <header className="bg-yotpo-purple border-b border-purple-900 sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        {/* Logo + nav */}
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-white/20 flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 5h10M3 8h7M3 11h5" stroke="white" strokeWidth="1.7" strokeLinecap="round"/>
              </svg>
            </div>
            <span className="text-white font-bold text-sm tracking-tight">Reviews Intelligence</span>
          </Link>

          <nav className="flex items-center gap-1">
            {links.map(l => (
              <Link
                key={l.to}
                to={l.to}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  loc.pathname === l.to
                    ? 'bg-white/20 text-white'
                    : 'text-purple-200 hover:text-white hover:bg-white/10'
                }`}
              >
                {l.label}
              </Link>
            ))}
          </nav>
        </div>

        {/* User */}
        {user && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              {user.photo ? (
                <img src={user.photo} alt={user.name} className="w-7 h-7 rounded-full ring-2 ring-white/30" />
              ) : (
                <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-white text-xs font-bold">
                  {(user.name || user.email)?.[0]?.toUpperCase()}
                </div>
              )}
              <span className="text-purple-200 text-sm hidden sm:block">{user.name}</span>
            </div>
            <button
              onClick={logout}
              className="text-xs text-purple-300 hover:text-white transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
