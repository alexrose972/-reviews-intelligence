import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../App.jsx'

// Official Yotpo wordmark (yotpo-logo-v3.svg), Yotpo blue.
function YotpoMark({ className = 'h-5' }) {
  return (
    <svg className={className} viewBox="0 0 113 32" xmlns="http://www.w3.org/2000/svg" aria-label="Yotpo">
      <g fill="none" fillRule="evenodd"><g fill="#0042E4"><g><g>
        <path d="M6.68 4.38l4.122 11.365L15.121 4.38h6.131L10.768 30.698H4.704l3.101-8.155L.352 4.38H6.68zm64.757-.403c5.536 0 9.573 4.296 9.573 10.176S76.973 24.33 71.437 24.33c-2.043 0-3.763-.541-5.076-1.584l-.085-.069-.073-.06v8.075h-5.908V4.38h5.224v1.967l.03-.034c1.287-1.468 3.234-2.28 5.64-2.333l.127-.002h.121zm-39.424 0c6.096 0 10.417 4.212 10.417 10.176 0 5.939-4.335 10.177-10.417 10.177-6.116 0-10.458-4.232-10.458-10.177 0-5.97 4.327-10.176 10.458-10.176zM52.273.05v4.33h4.86v5.103h-4.86v7.044c0 1.576.765 2.443 2.159 2.496l.068.001.069.001c.945 0 1.661-.248 2.302-.864l.06-.059.159-.163h.044v5.629l-.181.087c-.973.465-1.572.675-3.23.675-4.684 0-7.256-2.55-7.356-7.312l-.002-.145v-.145l-.001-7.245h-2.138V4.38h2.299V.05h5.747zM93.92 3.977c6.096 0 10.417 4.212 10.417 10.176 0 5.939-4.335 10.177-10.417 10.177-6.116 0-10.458-4.232-10.458-10.177 0-5.97 4.328-10.176 10.458-10.176zm15.233 13.878c1.788 0 3.237 1.45 3.237 3.237 0 1.788-1.45 3.238-3.237 3.238-1.788 0-3.237-1.45-3.237-3.238s1.45-3.237 3.237-3.237zM70.552 9.282c-2.662 0-4.47 1.97-4.47 4.871 0 2.902 1.808 4.872 4.47 4.872 2.696 0 4.51-1.964 4.51-4.872 0-2.907-1.814-4.871-4.51-4.871zm-38.54 0c-2.67 0-4.509 1.98-4.509 4.871 0 2.892 1.839 4.872 4.51 4.872 2.636 0 4.47-1.986 4.47-4.872 0-2.885-1.834-4.871-4.47-4.871zm61.908 0c-2.67 0-4.51 1.98-4.51 4.871 0 2.892 1.84 4.872 4.51 4.872 2.636 0 4.47-1.986 4.47-4.872 0-2.885-1.834-4.871-4.47-4.871z" transform="translate(-40 -20) translate(-3 -2) translate(43 22.5)"/>
      </g></g></g></g>
    </svg>
  )
}

export { YotpoMark }

export default function Nav() {
  const { user, logout } = useAuth()
  const loc = useLocation()

  const links = [
    { to: '/',        label: 'Scan' },
    { to: '/history', label: 'History' },
  ]

  return (
    <header className="bg-white/90 backdrop-blur border-b border-gray-200/80 sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        {/* Logo + nav */}
        <div className="flex items-center gap-7">
          <Link to="/" className="flex items-center gap-2.5">
            <YotpoMark className="h-5" />
            <span className="hidden sm:block h-4 w-px bg-gray-200" />
            <span className="hidden sm:block text-[13px] font-semibold text-gray-500 tracking-tight">
              Reviews Intelligence
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            {links.map(l => {
              const active = loc.pathname === l.to
              return (
                <Link
                  key={l.to}
                  to={l.to}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    active
                      ? 'bg-yotpo-pale text-yotpo-purple'
                      : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  {l.label}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* User */}
        {user && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              {user.photo ? (
                <img src={user.photo} alt={user.name} className="w-8 h-8 rounded-full ring-2 ring-yotpo-pale" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-yotpo-purple flex items-center justify-center text-white text-xs font-bold">
                  {(user.name || user.email)?.[0]?.toUpperCase()}
                </div>
              )}
              <span className="text-gray-700 text-sm font-medium hidden sm:block">{user.name}</span>
            </div>
            <button
              onClick={logout}
              className="text-xs font-medium text-gray-400 hover:text-gray-700 transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
