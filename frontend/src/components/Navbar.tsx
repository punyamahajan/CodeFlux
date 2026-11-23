import React from 'react'
import { User, api } from '../api'
import {
  Key,
  Shield,
  Zap,
  Route,
  Activity,
  LogOut,
  Swords,
  Play,
  Terminal,
} from 'lucide-react'

interface NavbarProps {
  user: User | null
  currentPath: string
  onNavigate: (path: string) => void
  onLogout: () => void
}

export const Navbar: React.FC<NavbarProps> = ({ user, currentPath, onNavigate, onLogout }) => {
  const handleLogout = async () => {
    try {
      await api.logout()
    } catch {
      // ignore
    }
    onLogout()
    onNavigate('/')
  }

  const navLink = (path: string, label: string, Icon: React.FC<{ className?: string }>) => {
    const isActive = currentPath === path
    return (
      <button
        onClick={() => onNavigate(path)}
        className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
          isActive
            ? 'bg-indigo-50 text-indigo-700 font-semibold border border-indigo-100 shadow-xs'
            : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/80'
        }`}
      >
        <Icon className="w-3.5 h-3.5" />
        <span>{label}</span>
      </button>
    )
  }

  return (
    <header className="sticky top-0 z-40 bg-white/85 backdrop-blur-md border-b border-slate-200/80 shadow-xs">
      {/* Top Demo Banner */}
      <div className="bg-amber-50/90 border-b border-amber-200/60 px-4 py-1 text-center text-xs font-medium text-amber-800">
        ⚠️ Demo environment, do not enter production keys.
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => onNavigate(user ? (user.role === 'admin' ? '/admin' : '/app') : '/')}>
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-violet-600 to-purple-600 flex items-center justify-center shadow-md shadow-indigo-500/20">
            <Zap className="w-5 h-5 text-white font-bold" />
          </div>
          <div>
            <span className="text-lg font-bold tracking-tight text-slate-900 flex items-center space-x-1.5">
              <span>OmniKey</span>
              <span className="text-[10px] px-2 py-0.5 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full font-mono font-semibold">
                v2.0
              </span>
            </span>
          </div>
        </div>

        {/* Links */}
        <nav className="hidden md:flex items-center space-x-1">
          {user?.role === 'admin' && (
            <>
              {navLink('/admin', 'Dashboard', Activity)}
              {navLink('/admin/vault', 'Vault', Shield)}
              {navLink('/admin/keys', 'Keys', Key)}
              {navLink('/admin/routes', 'Routes', Route)}
              {navLink('/admin/requests', 'Requests', Terminal)}
              {navLink('/admin/traces', 'Traces', Activity)}
            </>
          )}

          {user?.role === 'member' && (
            <>
              {navLink('/app', 'My Overview', Key)}
            </>
          )}

          {/* Playground and Arenas available to all authenticated users or public demo */}
          {navLink('/playground', 'Playground', Play)}
          {navLink('/arena/compare', 'Compare Arena', Swords)}
          {navLink('/arena/debate', 'Debate Arena', Swords)}
        </nav>

        {/* User / Auth action */}
        <div className="flex items-center space-x-3">
          {user ? (
            <div className="flex items-center space-x-3">
              <div className="text-right hidden sm:block">
                <p className="text-xs font-semibold text-slate-800">{user.email}</p>
                <p className="text-[10px] text-indigo-600 capitalize font-mono font-medium">{user.role}</p>
              </div>
              <button
                onClick={handleLogout}
                className="p-2 text-slate-400 hover:text-rose-600 hover:bg-slate-100 rounded-lg transition cursor-pointer"
                title="Log out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <button
                onClick={() => onNavigate('/auth')}
                className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition cursor-pointer"
              >
                Sign In / Sign Up
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
