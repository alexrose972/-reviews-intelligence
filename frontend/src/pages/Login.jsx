import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { YotpoMark } from '../components/Nav.jsx'

const ERROR_MSGS = {
  domain:   'This tool is for Yotpo team members only. Sign in with your @yotpo.com Google account.',
  oauth:    'Sign-in failed. Please try again.',
  no_code:  'Sign-in was cancelled. Please try again.',
}

export default function Login() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const error = params.get('error')

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [user])

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-yotpo-ink relative overflow-hidden">
      {/* Brand glow */}
      <div className="pointer-events-none absolute -top-40 -right-40 w-[36rem] h-[36rem] rounded-full bg-yotpo-purple/30 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-40 w-[32rem] h-[32rem] rounded-full bg-yotpo-accent/20 blur-3xl" />

      <div className="w-full max-w-sm relative animate-fade-up">
        <div className="bg-white rounded-2xl shadow-2xl p-8 text-center">
          {/* Logo */}
          <div className="flex items-center justify-center mb-5">
            <YotpoMark className="h-8" />
          </div>
          <div className="text-sm font-semibold text-gray-900">Reviews Intelligence</div>
          <p className="text-sm text-gray-500 mt-1.5 mb-6">
            Scan brands, score review experiences,<br />draft outreach — all in one place.
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100 text-red-700 text-sm text-left">
              {ERROR_MSGS[error] || 'Something went wrong. Please try again.'}
            </div>
          )}

          <a
            href="/auth/login"
            className="flex items-center justify-center gap-3 w-full px-4 py-3 rounded-xl border-2 border-gray-200 bg-white text-sm font-semibold text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-all"
          >
            <GoogleIcon />
            Sign in with Google
          </a>

          <p className="mt-4 text-xs text-gray-400">
            Yotpo team members only · @yotpo.com accounts
          </p>
        </div>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
      <path fill="#FBBC05" d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"/>
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z"/>
    </svg>
  )
}
