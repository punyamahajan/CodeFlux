import React, { useEffect, useState } from 'react'
import { api, ProviderCredential } from '../api'
import { Shield, Plus, Trash2, Power, AlertCircle, RefreshCw } from 'lucide-react'

export const AdminVault: React.FC = () => {
  const [credentials, setCredentials] = useState<ProviderCredential[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Add form
  const [showAdd, setShowAdd] = useState(false)
  const [provider, setProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const loadVault = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getVault()
      setCredentials(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadVault()
  }, [])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!apiKey.trim()) return
    setSubmitting(true)
    try {
      await api.addCredential({ provider, key: apiKey.trim() })
      setApiKey('')
      setShowAdd(false)
      await loadVault()
    } catch (err: any) {
      alert(`Failed to add credential: ${err.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleToggle = async (id: string, currentStatus: boolean) => {
    try {
      await api.toggleCredential(id, !currentStatus)
      await loadVault()
    } catch (err: any) {
      alert(`Failed to toggle credential: ${err.message}`)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to permanently delete this provider credential?')) return
    try {
      await api.deleteCredential(id)
      await loadVault()
    } catch (err: any) {
      alert(`Failed to delete credential: ${err.message}`)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Shield className="w-6 h-6 text-emerald-400" />
            <span>Encrypted Provider Key Vault</span>
          </h1>
          <p className="text-xs text-slate-400">
            Provider credentials are encrypted with AES-128-CBC / Fernet. Only the last 4 characters are ever revealed.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={loadVault}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-emerald-600/20 transition cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Add Provider Key</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Add dialog */}
      {showAdd && (
        <form onSubmit={handleAdd} className="p-6 bg-slate-900 border border-emerald-500/40 rounded-2xl space-y-4 shadow-xl animate-fade-in">
          <h3 className="text-sm font-semibold text-white">Add New Provider Credential</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Provider</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-emerald-500"
              >
                <option value="openai">OpenAI (sk-...)</option>
                <option value="gemini">Google Gemini (AQ...)</option>
                <option value="groq">Groq (gsk_...)</option>
                <option value="anthropic">Anthropic (sk-ant-...)</option>
                <option value="ollama">Ollama (local / remote)</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">Provider API Key</label>
              <input
                type="password"
                required
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste key here..."
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl text-xs font-medium hover:bg-slate-700 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition disabled:opacity-50"
            >
              {submitting ? 'Encrypting & Saving...' : 'Save Credential'}
            </button>
          </div>
        </form>
      )}

      {/* Credential Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 border-b border-slate-800 text-slate-400 uppercase tracking-wider font-semibold">
              <tr>
                <th className="py-3.5 px-4">Provider</th>
                <th className="py-3.5 px-4">Key Hint</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Last Used</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {credentials.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-500">
                    No provider keys in vault. Click "Add Provider Key" above.
                  </td>
                </tr>
              ) : (
                credentials.map((cred) => (
                  <tr key={cred.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-3.5 px-4 font-semibold text-slate-100 uppercase">{cred.provider}</td>
                    <td className="py-3.5 px-4 font-mono text-emerald-400">••••••••{cred.key_hint}</td>
                    <td className="py-3.5 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          cred.enabled
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {cred.enabled ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-slate-400">
                      {cred.last_used_at ? new Date(cred.last_used_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="py-3.5 px-4 text-right space-x-2">
                      <button
                        onClick={() => handleToggle(cred.id, cred.enabled)}
                        className={`p-1.5 rounded-lg border transition ${
                          cred.enabled
                            ? 'text-amber-400 hover:bg-amber-500/10 border-amber-500/20'
                            : 'text-emerald-400 hover:bg-emerald-500/10 border-emerald-500/20'
                        }`}
                        title={cred.enabled ? 'Disable key' : 'Enable key'}
                      >
                        <Power className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(cred.id)}
                        className="p-1.5 text-rose-400 hover:bg-rose-500/10 border border-rose-500/20 rounded-lg transition"
                        title="Delete key"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
