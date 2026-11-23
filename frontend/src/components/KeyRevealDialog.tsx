import React, { useState } from 'react'
import { Check, Copy, AlertTriangle, Key } from 'lucide-react'

interface KeyRevealDialogProps {
  apiKey: string
  keyName: string
  onClose: () => void
}

export const KeyRevealDialog: React.FC<KeyRevealDialogProps> = ({ apiKey, keyName, onClose }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(apiKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const curlSnippet = `curl http://localhost:8000/v1/chat/completions \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello OmniKey!"}]
  }'`

  const pythonSnippet = `from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="${apiKey}",
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello OmniKey!"}],
)
print(response.choices[0].message.content)`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-white border border-slate-200/90 rounded-2xl w-full max-w-2xl p-6 shadow-2xl space-y-5">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-gradient-to-tr from-indigo-50 to-violet-50 border border-indigo-100 rounded-xl text-indigo-600">
            <Key className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900">Platform Key Created: {keyName}</h3>
            <p className="text-xs text-slate-500">Save this key now. It will never be shown again.</p>
          </div>
        </div>

        <div className="p-4 bg-amber-50 border border-amber-200/80 rounded-xl flex items-start space-x-3">
          <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-amber-800 leading-relaxed font-medium">
            Copy and store this secret securely. For security, OmniKey only retains an HMAC-SHA256 digest
            in the database and cannot recover the plaintext key once you close this dialog.
          </p>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider block mb-1.5">
            Your Secret API Key
          </label>
          <div className="flex items-center space-x-2">
            <input
              type="text"
              readOnly
              value={apiKey}
              className="flex-1 px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-mono font-semibold text-indigo-700 focus:outline-none select-all shadow-inner"
            />
            <button
              onClick={handleCopy}
              className="px-4 py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 shadow-md shadow-indigo-500/20 transition cursor-pointer"
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              <span>{copied ? 'Copied' : 'Copy Key'}</span>
            </button>
          </div>
        </div>

        {/* Code Snippets */}
        <div className="space-y-3 pt-2 border-t border-slate-100">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider block">
            Quickstart Snippets
          </span>

          <div>
            <span className="text-[11px] text-slate-500 font-mono mb-1 block">cURL:</span>
            <pre className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-emerald-400 overflow-x-auto">
              {curlSnippet}
            </pre>
          </div>

          <div>
            <span className="text-[11px] text-slate-500 font-mono mb-1 block">Python (OpenAI SDK):</span>
            <pre className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-xs font-mono text-emerald-400 overflow-x-auto">
              {pythonSnippet}
            </pre>
          </div>
        </div>

        <div className="flex justify-end pt-3">
          <button
            onClick={onClose}
            className="px-5 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-semibold transition cursor-pointer"
          >
            I have saved my key
          </button>
        </div>
      </div>
    </div>
  )
}
