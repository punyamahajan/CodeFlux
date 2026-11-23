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
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center space-x-2">
            <div className="p-1.5 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600">
              <Key className="w-5 h-5" />
            </div>
            <span>Member Workspace</span>
          </h1>
          <p className="text-xs text-slate-500">
            View your active keys, monitor credit balances, and request limit increases.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={loadData}
            className="p-2 bg-white hover:bg-slate-50 text-slate-600 border border-slate-200/80 rounded-xl transition cursor-pointer shadow-xs"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowRequest(!showRequest)}
            className="px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200/80 rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-xs transition cursor-pointer"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Request Limit Increase</span>
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-4 py-2 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-md shadow-indigo-500/25 transition cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Create Key</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Request limit form */}
      {showRequest && (
        <form onSubmit={handleRequestCredits} className="p-6 bg-white border border-indigo-200 rounded-2xl space-y-4 shadow-xl shadow-indigo-100/40 animate-fade-in">
          <h3 className="text-sm font-semibold text-slate-900">Request Credit Limit Increase</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-slate-700 block mb-1">Target Key</label>
              <select
                value={reqKeyId}
                onChange={(e) => setReqKeyId(e.target.value)}
                className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
              >
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name} ({k.key_prefix}••••)
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-700 block mb-1">Requested Limit (USD)</label>
              <input
                type="number"
                step="1"
                min="1"
                required
                value={reqDollars}
                onChange={(e) => setReqDollars(e.target.value)}
                className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-700 block mb-1">Reason for Increase</label>
              <input
                type="text"
                required
                value={reqReason}
                onChange={(e) => setReqReason(e.target.value)}
                placeholder="Testing prompt evals..."
                className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowRequest(false)}
              className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-xl text-xs font-semibold hover:bg-slate-50 transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submittingReq}
              className="px-5 py-2 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/25 transition cursor-pointer"
            >
              {submittingReq ? 'Submitting...' : 'Send Request to Admin'}
            </button>
          </div>
        </form>
      )}

      {/* Create Key modal */}
      {showCreate && (
        <form onSubmit={handleCreateKey} className="p-6 bg-white border border-indigo-200 rounded-2xl space-y-4 shadow-xl shadow-indigo-100/40 animate-fade-in">
          <h3 className="text-sm font-semibold text-slate-900">Create New Key</h3>
          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">Key Name</label>
            <input
              type="text"
              required
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="e.g. My Dev Script"
              className="w-full px-3.5 py-2 bg-white border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
            />
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-xl text-xs font-semibold hover:bg-slate-50 transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/25 transition cursor-pointer"
            >
              Create
            </button>
          </div>
        </form>
      )}

      {/* My Keys list */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 space-y-4 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">Your Platform Keys</h2>
        <div className="divide-y divide-slate-100">
          {keys.length === 0 ? (
            <p className="py-8 text-center text-xs text-slate-400">
              No keys yet. Click "Create Key" to get your first OmniKey.
            </p>
          ) : (
            keys.map((k) => (
              <div key={k.id} className="py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-slate-900">{k.name}</span>
                    <span className="font-mono text-xs text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100 font-medium">
                      {k.key_prefix}••••
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500">
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
