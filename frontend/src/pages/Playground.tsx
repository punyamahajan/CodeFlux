import React, { useState } from 'react'
import { api } from '../api'
import { Play, Send, AlertCircle } from 'lucide-react'
import { WhyButton } from '../components/WhyButton'
import { WhyPanel } from '../components/WhyPanel'

export const Playground: React.FC = () => {
  const [format, setFormat] = useState<'openai' | 'gemini'>('openai')
  const [model, setModel] = useState('gpt-4o-mini')
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([
    { role: 'user', content: 'Explain quantum computing in two sentences.' },
  ])
  const [input, setInput] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<any>(null)
  const [whyTraceId, setWhyTraceId] = useState<string | null>(null)

  const handleSend = async () => {
    if (!input.trim() && messages.length === 0) return
    const currentMsgs = input.trim()
      ? [...messages, { role: 'user', content: input.trim() }]
      : messages

    if (input.trim()) {
      setMessages(currentMsgs)
      setInput('')
    }

    setLoading(true)
    setError(null)
    try {
      const data = await api.playgroundChat({
        format,
        model,
        messages: currentMsgs,
      })
      setResponse(data)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }])
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8 py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <Play className="w-6 h-6 text-emerald-400" />
            <span>Interactive Playground</span>
          </h1>
          <p className="text-xs text-slate-400">
            Send requests through the real OmniKey gateway path in OpenAI or Gemini JSON formats.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl p-1 text-xs">
            <button
              onClick={() => setFormat('openai')}
              className={`px-3 py-1 rounded-lg font-medium transition ${
                format === 'openai' ? 'bg-emerald-500/20 text-emerald-400' : 'text-slate-400'
              }`}
            >
              OpenAI Schema
            </button>
            <button
              onClick={() => setFormat('gemini')}
              className={`px-3 py-1 rounded-lg font-medium transition ${
                format === 'gemini' ? 'bg-emerald-500/20 text-emerald-400' : 'text-slate-400'
              }`}
            >
              Gemini Schema
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-2xl text-rose-300 text-sm flex items-center space-x-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chat Conversation pane */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl flex flex-col h-[580px] shadow-xl overflow-hidden">
          <div className="p-4 bg-slate-950/60 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="text-xs font-semibold text-slate-300">Model:</span>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="gpt-4o-mini, smart, fast..."
                className="px-2.5 py-1 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-emerald-400 focus:outline-none w-48"
              />
            </div>
            <button
              onClick={() => {
                setMessages([])
                setResponse(null)
              }}
              className="text-xs text-slate-400 hover:text-white"
            >
              Clear Chat
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-4">
            {messages.length === 0 ? (
              <p className="text-xs text-slate-500 text-center py-20 italic">
                No messages yet. Type a prompt below and send!
              </p>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`flex flex-col ${
                    m.role === 'user' ? 'items-end' : 'items-start'
                  }`}
                >
                  <span className="text-[10px] text-slate-500 uppercase font-semibold mb-1">
                    {m.role}
                  </span>
                  <div
                    className={`p-3 rounded-2xl text-xs max-w-[85%] leading-relaxed ${
                      m.role === 'user'
                        ? 'bg-emerald-600 text-white rounded-br-none'
                        : 'bg-slate-800 text-slate-200 border border-slate-700 rounded-bl-none'
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="p-3 bg-slate-950/60 border-t border-slate-800 flex items-center space-x-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !loading && handleSend()}
              placeholder="Ask anything or test a model prompt..."
              className="flex-1 px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-white focus:outline-none focus:border-emerald-500"
            />
            <button
              onClick={handleSend}
              disabled={loading}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition disabled:opacity-50 cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{loading ? 'Sending...' : 'Send'}</span>
            </button>
          </div>
        </div>

        {/* Response Metadata & Raw Payloads */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col h-[580px] shadow-xl overflow-hidden space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-semibold text-white">Gateway Inspection</h3>
            {response?.trace_id && (
              <WhyButton
                onClick={() => setWhyTraceId(response.trace_id)}
                label="Why this routing & cost?"
              />
            )}
          </div>

          {response ? (
            <div className="space-y-4 overflow-y-auto flex-1 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 bg-slate-950 rounded-xl border border-slate-800">
                <div>
                  <span className="text-slate-400 block text-[11px]">Provider Used:</span>
                  <span className="font-semibold text-emerald-400 uppercase">{response.provider}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Latency:</span>
                  <span className="font-mono">{response.latency_ms} ms</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Total Tokens:</span>
                  <span className="font-mono">{response.tokens?.total_tokens}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Trace ID:</span>
                  <span className="font-mono text-[10px] text-slate-300">{response.trace_id?.slice(0, 16)}...</span>
                </div>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                  Raw Gateway Request ({format})
                </span>
                <pre className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-[11px] font-mono text-slate-300 overflow-x-auto max-h-40">
                  {JSON.stringify(response.raw_request, null, 2)}
                </pre>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                  Raw Upstream Response ({format})
                </span>
                <pre className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-[11px] font-mono text-slate-300 overflow-x-auto max-h-48">
                  {JSON.stringify(response.raw_response, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="py-24 text-center text-xs text-slate-500">
              Send a message on the left to inspect raw payloads, token counts, and the Explain Why engine.
            </div>
          )}
        </div>
      </div>

      {whyTraceId && (
        <WhyPanel
          kind="trace"
          id={whyTraceId}
          onClose={() => setWhyTraceId(null)}
        />
      )}
    </div>
  )
}
