import React, { useEffect, useState, useCallback } from 'react'
import { api, PlatformKey } from '../api'
import { Key, Plus, Send, AlertCircle, RefreshCw } from 'lucide-react'
import { UsageBar } from '../components/UsageBar'
import { KeyRevealDialog } from '../components/KeyRevealDialog'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const MemberApp: React.FC = () => {
  const [keys, setKeys] = useState<PlatformKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create key
  const [showCreate, setShowCreate] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [newKey, setNewKey] = useState<{ plaintext: string; name: string } | null>(null)

  // Request more credits
  const [showRequest, setShowRequest] = useState(false)
  const [reqKeyId, setReqKeyId] = useState('')
  const [reqDollars, setReqDollars] = useState('10')
  const [reqReason, setReqReason] = useState('')
  const [submittingReq, setSubmittingReq] = useState(false)

  const [whyKeyId, setWhyKeyId] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const k = await api.getMemberKeys()
      setKeys(k)
      if (k.length > 0 && !reqKeyId) {
        setReqKeyId(k[0].id)
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [reqKeyId])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!keyName.trim()) return
    try {
      const res = await api.createMemberKey({ name: keyName.trim() })
      setKeyName('')
      setShowCreate(false)
      setNewKey({ plaintext: res.plaintext, name: res.key.name })
      await loadData()
    } catch (err: any) {
      alert(`Key creation failed: ${err.message}`)
    }
  }

  const handleRequestCredits = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reqKeyId || !reqReason.trim()) return
    setSubmittingReq(true)
    try {
      const micro = Math.round(parseFloat(reqDollars) * 1_000_000)
      await api.createLimitRequest({
        key_id: reqKeyId,
        requested_credit_micro: micro,
        reason: reqReason.trim(),
      })
      alert('Credit increase request submitted to admin!')
      setShowRequest(false)
      setReqReason('')
      await loadData()
    } catch (err: any) {
      alert(`Request failed: ${err.message}`)
    } finally {
      setSubmittingReq(false)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Key className="w-6 h-6 text-emerald-400" />
            <span>Member Workspace</span>
          </h1>
          <p className="text-xs text-slate-400">
            View your active keys, monitor credit balances, and request limit increases.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={loadData}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowRequest(!showRequest)}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Request Limit Increase</span>
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-emerald-600/20 transition cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Create Key</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Request limit form */}
      {showRequest && (
        <form onSubmit={handleRequestCredits} className="p-6 bg-slate-900 border border-purple-500/40 rounded-2xl space-y-4 shadow-xl animate-fade-in">
          <h3 className="text-sm font-semibold text-white">Request Credit Limit Increase</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Target Key</label>
              <select
                value={reqKeyId}
                onChange={(e) => setReqKeyId(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none"
              >
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name} ({k.key_prefix}••••)
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Requested Limit (USD)</label>
              <input
                type="number"
                step="1"
                min="1"
                required
                value={reqDollars}
                onChange={(e) => setReqDollars(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white font-mono focus:outline-none"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Reason for Increase</label>
              <input
                type="text"
                required
                value={reqReason}
                onChange={(e) => setReqReason(e.target.value)}
                placeholder="Testing prompt evals..."
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowRequest(false)}
              className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl text-xs hover:bg-slate-700 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submittingReq}
              className="px-5 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-semibold transition"
            >
              {submittingReq ? 'Submitting...' : 'Send Request to Admin'}
            </button>
          </div>
        </form>
      )}

      {/* Create Key modal */}
      {showCreate && (
        <form onSubmit={handleCreateKey} className="p-6 bg-slate-900 border border-emerald-500/40 rounded-2xl space-y-4 shadow-xl animate-fade-in">
          <h3 className="text-sm font-semibold text-white">Create New Key</h3>
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1">Key Name</label>
            <input
              type="text"
              required
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="e.g. My Dev Script"
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none"
            />
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl text-xs hover:bg-slate-700 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition"
            >
              Create
            </button>
          </div>
        </form>
      )}

      {/* My Keys list */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-xl">
        <h2 className="text-base font-semibold text-white">Your Platform Keys</h2>
        <div className="divide-y divide-slate-800/60">
          {keys.length === 0 ? (
            <p className="py-8 text-center text-xs text-slate-500">
              No keys yet. Click "Create Key" to get your first OmniKey.
            </p>
          ) : (
            keys.map((k) => (
              <div key={k.id} className="py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-slate-100">{k.name}</span>
                    <span className="font-mono text-xs text-emerald-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                      {k.key_prefix}••••
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    RPM limit: {k.rpm_limit} • Created {new Date(k.created_at).toLocaleDateString()}
                  </p>
                </div>

                <div className="w-full sm:w-64 space-y-1">
                  <UsageBar
                    remainingMicro={k.credit_remaining_micro}
                    limitMicro={k.credit_limit_micro}
                  />
                  <div className="flex justify-end">
                    <WhyButton onClick={() => setWhyKeyId(k.id)} />
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {newKey && (
        <KeyRevealDialog
          apiKey={newKey.plaintext}
          keyName={newKey.name}
          onClose={() => setNewKey(null)}
        />
      )}

      {whyKeyId && (
        <WhyPanel
          kind="credits"
          id={whyKeyId}
          onClose={() => setWhyKeyId(null)}
        />
      )}
    </div>
  )
}
