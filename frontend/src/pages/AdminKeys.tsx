import React, { useEffect, useState } from 'react'
import { api, PlatformKey } from '../api'
import { Key, Plus, Ban, RefreshCw, AlertCircle } from 'lucide-react'
import { UsageBar } from '../components/UsageBar'
import { KeyRevealDialog } from '../components/KeyRevealDialog'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const AdminKeys: React.FC = () => {
  const [keys, setKeys] = useState<PlatformKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Creation modal
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [limitDollars, setLimitDollars] = useState('10')
  const [rpmLimit, setRpmLimit] = useState(60)
  const [submitting, setSubmitting] = useState(false)

  // Newly created key reveal
  const [newKey, setNewKey] = useState<{ plaintext: string; name: string } | null>(null)
  const [whyKeyId, setWhyKeyId] = useState<string | null>(null)

  const loadKeys = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getKeys()
      setKeys(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadKeys()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSubmitting(true)
    try {
      const limitMicro = Math.round(parseFloat(limitDollars || '0') * 1_000_000)
      const res = await api.createKey({
        name: name.trim(),
        credit_limit_micro: limitMicro,
        rpm_limit: rpmLimit,
      })
      setName('')
      setShowCreate(false)
      const plain = (res as any).plaintext || (res as any).key || (res as any).raw_key
      const keyName = (res as any).name || (res as any).key?.name || name.trim()
      setNewKey({ plaintext: plain, name: keyName })
      await loadKeys()
    } catch (err: any) {
      alert(`Failed to create key: ${err.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevoke = async (id: string) => {
    if (!confirm('Are you sure you want to revoke this platform key? This cannot be undone.')) return
    try {
      await api.revokeKey(id)
      await loadKeys()
    } catch (err: any) {
      alert(`Failed to revoke key: ${err.message}`)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Key className="w-6 h-6 text-emerald-400" />
            <span>Platform API Keys</span>
          </h1>
          <p className="text-xs text-slate-400">
            Issue prefixed <code className="text-emerald-400 font-mono">ok_live_</code> keys with strict credit and RPM limits.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={loadKeys}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-emerald-600/20 transition cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Generate Platform Key</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <form onSubmit={handleCreate} className="p-6 bg-slate-900 border border-emerald-500/40 rounded-2xl space-y-4 shadow-xl animate-fade-in">
          <h3 className="text-sm font-semibold text-white">Generate New Platform Key</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Key Name / Description</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Production Backend"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Credit Limit (USD)</label>
              <input
                type="number"
                step="0.5"
                min="0.1"
                required
                value={limitDollars}
                onChange={(e) => setLimitDollars(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">RPM Limit (req/min)</label>
              <input
                type="number"
                min="1"
                required
                value={rpmLimit}
                onChange={(e) => setRpmLimit(parseInt(e.target.value, 10))}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl text-xs font-medium hover:bg-slate-700 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition disabled:opacity-50"
            >
              {submitting ? 'Generating...' : 'Create Key'}
            </button>
          </div>
        </form>
      )}

      {/* Keys Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 border-b border-slate-800 text-slate-400 uppercase tracking-wider font-semibold">
              <tr>
                <th className="py-3.5 px-4">Key Name</th>
                <th className="py-3.5 px-4">Prefix</th>
                <th className="py-3.5 px-4 min-w-[200px]">Credits Balance</th>
                <th className="py-3.5 px-4">RPM</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {keys.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500">
                    No platform keys created yet. Generate one above!
                  </td>
                </tr>
              ) : (
                keys.map((k) => (
                  <tr key={k.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-3.5 px-4 font-semibold text-slate-100">{k.name}</td>
                    <td className="py-3.5 px-4 font-mono text-emerald-400">{k.key_prefix}••••</td>
                    <td className="py-3.5 px-4">
                      <div className="flex items-center space-x-2">
                        <div className="flex-1">
                          <UsageBar
                            remainingMicro={k.credit_remaining_micro}
                            limitMicro={k.credit_limit_micro}
                          />
                        </div>
                        <WhyButton onClick={() => setWhyKeyId(k.id)} />
                      </div>
                    </td>
                    <td className="py-3.5 px-4 font-mono">{k.rpm_limit} / min</td>
                    <td className="py-3.5 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          k.revoked_at
                            ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                            : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        }`}
                      >
                        {k.revoked_at ? 'Revoked' : 'Active'}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      {!k.revoked_at && (
                        <button
                          onClick={() => handleRevoke(k.id)}
                          className="p-1.5 text-rose-400 hover:bg-rose-500/10 border border-rose-500/20 rounded-lg transition"
                          title="Revoke key"
                        >
                          <Ban className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
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
