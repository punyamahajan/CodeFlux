import React, { useEffect, useState } from 'react'
import { api, LimitRequest } from '../api'
import { Terminal, Check, X, RefreshCw, AlertCircle } from 'lucide-react'
import { formatMicroUSD } from '../utils'

export const AdminRequests: React.FC = () => {
  const [requests, setRequests] = useState<LimitRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLimitDollars, setEditLimitDollars] = useState('')

  const loadRequests = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getAdminRequests()
      setRequests(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRequests()
  }, [])

  const handleApprove = async (req: LimitRequest) => {
    try {
      let approvedMicro: number | undefined
      if (editingId === req.id && editLimitDollars) {
        approvedMicro = Math.round(parseFloat(editLimitDollars) * 1_000_000)
      } else {
        approvedMicro = req.requested_credit_micro
      }
      await api.approveRequest(req.id, approvedMicro)
      setEditingId(null)
      await loadRequests()
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`)
    }
  }

  const handleDeny = async (id: string) => {
    try {
      await api.denyRequest(id)
      await loadRequests()
    } catch (err: any) {
      alert(`Denial failed: ${err.message}`)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center space-x-2">
            <div className="p-1.5 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600">
              <Terminal className="w-5 h-5" />
            </div>
            <span>Member Limit Increase Requests</span>
          </h1>
          <p className="text-xs text-slate-500">
            Review and adjust credit limits requested by team members.
          </p>
        </div>
        <button
          onClick={loadRequests}
          className="p-2 bg-white hover:bg-slate-50 text-slate-600 border border-slate-200/80 rounded-xl transition self-start sm:self-auto cursor-pointer shadow-xs"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="bg-white border border-slate-200/80 rounded-2xl overflow-hidden shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50/80 border-b border-slate-200/80 text-slate-500 uppercase tracking-wider font-semibold text-[11px]">
              <tr>
                <th className="py-3.5 px-4">Member / Key</th>
                <th className="py-3.5 px-4">Current Limit</th>
                <th className="py-3.5 px-4">Requested Limit</th>
                <th className="py-3.5 px-4">Reason</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {requests.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    No credit limit requests pending.
                  </td>
                </tr>
              ) : (
                requests.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/60 transition">
                    <td className="py-3.5 px-4">
                      <p className="font-semibold text-slate-900">{r.user_email || r.user_id}</p>
                      <p className="text-[11px] text-slate-500 font-mono">{r.key_name || r.key_id}</p>
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-600">
                      {formatMicroUSD(r.current_limit_micro)}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-indigo-600 font-semibold">
                      {editingId === r.id ? (
                        <div className="flex items-center space-x-1">
                          <span>$</span>
                          <input
                            type="number"
                            step="1"
                            value={editLimitDollars}
                            onChange={(e) => setEditLimitDollars(e.target.value)}
                            className="w-20 px-2 py-1 bg-white border border-slate-300 rounded text-xs text-slate-900"
                          />
                        </div>
                      ) : (
                        formatMicroUSD(r.requested_credit_micro)
                      )}
                    </td>
                    <td className="py-3.5 px-4 max-w-xs truncate text-slate-700" title={r.reason}>
                      {r.reason}
                    </td>
                    <td className="py-3.5 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium capitalize ${
                          r.status === 'pending'
                            ? 'bg-amber-50 text-amber-700 border border-amber-200'
                            : r.status === 'approved'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/80'
                            : 'bg-rose-50 text-rose-700 border border-rose-200'
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right space-x-2">
                      {r.status === 'pending' && (
                        <>
                          {editingId !== r.id ? (
                            <button
                              onClick={() => {
                                setEditingId(r.id)
                                setEditLimitDollars(
                                  (r.requested_credit_micro / 1_000_000).toString()
                                )
                              }}
                              className="px-2.5 py-1 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg text-xs bg-white hover:bg-slate-50 transition cursor-pointer"
                            >
                              Edit
                            </button>
                          ) : (
                            <button
                              onClick={() => setEditingId(null)}
                              className="px-2.5 py-1 text-slate-500 hover:text-slate-700 text-xs"
                            >
                              Cancel
                            </button>
                          )}
                          <button
                            onClick={() => handleApprove(r)}
                            className="p-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-lg transition shadow-xs cursor-pointer inline-flex items-center"
                            title="Approve limit"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleDeny(r.id)}
                            className="p-1.5 text-rose-600 hover:bg-rose-50 border border-rose-200 rounded-lg transition cursor-pointer inline-flex items-center"
                            title="Deny limit"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
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
