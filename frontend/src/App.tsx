import React, { useEffect, useState } from 'react'
import { api, User } from './api'
import { Navbar } from './components/Navbar'
import { Home } from './pages/Home'
import { Auth } from './pages/Auth'
import { AdminDashboard } from './pages/AdminDashboard'
import { AdminVault } from './pages/AdminVault'
import { AdminKeys } from './pages/AdminKeys'
import { AdminRoutes } from './pages/AdminRoutes'
import { AdminRequests } from './pages/AdminRequests'
import { AdminTraces } from './pages/AdminTraces'
import { MemberApp } from './pages/MemberApp'
import { Playground } from './pages/Playground'
import { ArenaCompare } from './pages/ArenaCompare'
import { ArenaDebate } from './pages/ArenaDebate'

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(null)
  const [checkingAuth, setCheckingAuth] = useState(true)
  const [currentPath, setCurrentPath] = useState<string>(window.location.pathname || '/')

  const navigate = (path: string) => {
    window.history.pushState({}, '', path)
    setCurrentPath(path)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  useEffect(() => {
    const handlePop = () => {
      setCurrentPath(window.location.pathname || '/')
    }
    window.addEventListener('popstate', handlePop)
    return () => window.removeEventListener('popstate', handlePop)
  }, [])

  useEffect(() => {
    api
      .me()
      .then((u) => {
        setUser(u)
      })
      .catch(() => {
        setUser(null)
      })
      .finally(() => {
        setCheckingAuth(false)
      })
  }, [])

  const handleLoginSuccess = (u: User) => {
    setUser(u)
    if (u.role === 'admin') {
      navigate('/admin')
    } else {
      navigate('/app')
    }
  }

  const handleLogout = () => {
    setUser(null)
  }

  if (checkingAuth) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center space-y-3">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-xs text-slate-400 font-medium">Checking OmniKey session...</p>
      </div>
    )
  }

  // Route Guarding
  const isAdminRoute = currentPath.startsWith('/admin')
  const isMemberRoute = currentPath === '/app'

  let content: React.ReactNode

  if (isAdminRoute && user?.role !== 'admin') {
    content = (
      <div className="max-w-md mx-auto my-24 p-8 bg-slate-900 border border-slate-800 rounded-3xl text-center space-y-4">
        <h2 className="text-lg font-bold text-white">Admin Privileges Required</h2>
        <p className="text-xs text-slate-400">
          You must be signed in as an administrator to access {currentPath}.
        </p>
        <button
          onClick={() => navigate('/auth')}
          className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold"
        >
          Sign in as Admin
        </button>
      </div>
    )
  } else if (isMemberRoute && !user) {
    content = (
      <div className="max-w-md mx-auto my-24 p-8 bg-slate-900 border border-slate-800 rounded-3xl text-center space-y-4">
        <h2 className="text-lg font-bold text-white">Sign In Required</h2>
        <p className="text-xs text-slate-400">Please log in to view your workspace and keys.</p>
        <button
          onClick={() => navigate('/auth')}
          className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold"
        >
          Sign in
        </button>
      </div>
    )
  } else {
    switch (currentPath) {
      case '/':
        content = <Home onNavigate={navigate} />
        break
      case '/auth':
        content = <Auth onSuccess={handleLoginSuccess} />
        break
      case '/admin':
        content = <AdminDashboard />
        break
      case '/admin/vault':
        content = <AdminVault />
        break
      case '/admin/keys':
        content = <AdminKeys />
        break
      case '/admin/routes':
        content = <AdminRoutes />
        break
      case '/admin/requests':
        content = <AdminRequests />
        break
      case '/admin/traces':
        content = <AdminTraces />
        break
      case '/app':
        content = <MemberApp />
        break
      case '/playground':
        content = <Playground />
        break
      case '/arena/compare':
        content = <ArenaCompare />
        break
      case '/arena/debate':
        content = <ArenaDebate />
        break
      default:
        content = <Home onNavigate={navigate} />
        break
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col text-slate-100">
      <Navbar
        user={user}
        currentPath={currentPath}
        onNavigate={navigate}
        onLogout={handleLogout}
      />
      <main className="flex-1">{content}</main>
      <footer className="border-t border-slate-900 bg-slate-950/80 py-8 px-4 text-center text-xs text-slate-500">
        <p>© 2026 OmniKey AI Gateway • Apache 2.0 • Deterministic Explainability Architecture</p>
      </footer>
    </div>
  )
}
