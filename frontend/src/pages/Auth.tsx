import React, { useState } from 'react'
import { api, User } from '../api'
import { Shield, UserPlus, LogIn, AlertCircle } from 'lucide-react'

interface AuthProps {
  onSuccess: (user: User) => void
}

export const Auth: React.FC<AuthProps> = ({ onSuccess }) => {
  const [tab, setTab] = useState<'login' | 'signup'>('login')
  const [signupType, setSignupType] = useState<'admin' | 'member'>('admin')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [orgName, setOrgName] = useState('')
  const [inviteCode, setInviteCode] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      if (tab === 'login') {
        const res = await api.login({ email, password })
        onSuccess(res.user)
      } else {
        const payload: any = { email, password }
        if (signupType === 'admin') {
          if (!orgName.trim()) {
            throw new Error('Workspace name is required for admin sign up')
          }
          payload.org_name = orgName.trim()
        } else {
          if (!inviteCode.trim()) {
            throw new Error('Invite code is required for member sign up')
          }
          payload.invite_code = inviteCode.trim()
        }
        const res = await api.signup(payload)
        onSuccess(res.user)
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 sm:px-6 lg:px-8 py-12">
      <div className="w-full max-w-md bg-white border border-slate-200/80 rounded-3xl p-8 shadow-xl shadow-slate-200/50 space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex p-3 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 mb-2 shadow-xs">
            <Shield className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
            {tab === 'login' ? 'Sign in to OmniKey' : 'Create an Account'}
          </h2>
          <p className="text-xs text-slate-500">
            {tab === 'login'
              ? 'Access your unified AI gateway and keys'
              : 'Start pooling provider keys and managing access'}
          </p>
        </div>

        {/* Tab switch */}
        <div className="flex bg-slate-100 p-1 rounded-xl border border-slate-200/60">
          <button
            type="button"
            onClick={() => {
              setTab('login')
              setError(null)
            }}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg flex items-center justify-center space-x-1.5 transition cursor-pointer ${
              tab === 'login'
                ? 'bg-white text-slate-900 shadow-xs'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <LogIn className="w-3.5 h-3.5" />
            <span>Login</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setTab('signup')
              setError(null)
            }}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg flex items-center justify-center space-x-1.5 transition cursor-pointer ${
              tab === 'signup'
                ? 'bg-white text-slate-900 shadow-xs'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Sign Up</span>
          </button>
        </div>

        {error && (
          <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-xs flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === 'signup' && (
            <div className="space-y-3 pb-3 border-b border-slate-100">
              <span className="text-xs font-medium text-slate-700 block">Account Type:</span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setSignupType('admin')}
                  className={`py-2 px-3 rounded-xl border text-xs font-medium transition flex flex-col items-center justify-center space-y-1 cursor-pointer ${
                    signupType === 'admin'
                      ? 'bg-indigo-50/70 border-indigo-400 text-indigo-900 shadow-xs'
                      : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
                  }`}
                >
                  <span className="font-semibold">Admin</span>
                  <span className="text-[10px] text-slate-500">Creates workspace</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSignupType('member')}
                  className={`py-2 px-3 rounded-xl border text-xs font-medium transition flex flex-col items-center justify-center space-y-1 cursor-pointer ${
                    signupType === 'member'
                      ? 'bg-indigo-50/70 border-indigo-400 text-indigo-900 shadow-xs'
                      : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
                  }`}
                >
                  <span className="font-semibold">Member</span>
                  <span className="text-[10px] text-slate-500">Joins with invite</span>
                </button>
              </div>

              {signupType === 'admin' ? (
                <div>
                  <label className="text-xs font-medium text-slate-700 block mb-1">
                    Workspace / Org Name
                  </label>
                  <input
                    type="text"
                    required
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="Acme Corp"
                    className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                  />
                </div>
              ) : (
                <div>
                  <label className="text-xs font-medium text-slate-700 block mb-1">
                    Organization Invite Code
                  </label>
                  <input
                    type="text"
                    required
                    value={inviteCode}
                    onChange={(e) => setInviteCode(e.target.value)}
                    placeholder="org_xxxx"
                    className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                  />
                </div>
              )}
            </div>
          )}

          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">Email Address</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
              className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">Password</label>
            <input
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-indigo-500/25 transition disabled:opacity-50 cursor-pointer"
          >
            {loading
              ? 'Processing...'
              : tab === 'login'
              ? 'Sign In'
              : signupType === 'admin'
              ? 'Create Workspace & Account'
              : 'Join Workspace'}
          </button>
        </form>
      </div>
    </div>
  )
}
