import React from 'react'
import { Zap, ShieldCheck, Cpu, ArrowRight, Layers, FileQuestion, Sparkles, CheckCircle2 } from 'lucide-react'

interface HomeProps {
  onNavigate: (path: string) => void
}

export const Home: React.FC<HomeProps> = ({ onNavigate }) => {
  const beforeCode = `# Before: Multiple SDKs, hardcoded API keys, no unified failover
import openai
import anthropic
import google.generativeai as genai

# Fragmented billing, no explainability, outages break everything`

  const afterCode = `# After: One key. Every model. Automatic failover and transparent reasoning.
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="ok_live_your_omnikey_here",
)

# Route by speed, cost, or task tag with complete auditability
response = client.chat.completions.create(
    model="smart",
    messages=[{"role": "user", "content": "Explain quantum entanglement"}],
)`

  return (
    <div className="space-y-24 py-12 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      {/* Hero */}
      <div className="text-center space-y-6 max-w-3xl mx-auto">
        <div className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-full bg-indigo-50/80 border border-indigo-200/80 text-indigo-700 text-xs font-semibold shadow-xs">
          <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
          <span>Unified AI Gateway with Transparent Reasoning</span>
        </div>
        <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight text-slate-900 leading-tight">
          One key.{' '}
          <span className="bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 bg-clip-text text-transparent">
            Every model.
          </span>
        </h1>
        <p className="text-lg text-slate-600 leading-relaxed max-w-2xl mx-auto">
          Pool your OpenAI, Anthropic, Gemini, Groq, and Ollama provider keys.
          Issue rate-limited platform keys to your team, route with instant fallback, and understand every single dollar and routing decision with deterministic explainability.
        </p>
        <div className="flex items-center justify-center space-x-4 pt-4">
          <button
            onClick={() => onNavigate('/auth')}
            className="px-6 py-3 bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 hover:from-indigo-500 hover:to-violet-500 text-white font-semibold rounded-xl shadow-lg shadow-indigo-500/25 flex items-center space-x-2 transition cursor-pointer"
          >
            <span>Get Started Free</span>
            <ArrowRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => onNavigate('/playground')}
            className="px-6 py-3 bg-white hover:bg-slate-50 text-slate-700 font-semibold rounded-xl border border-slate-200/80 shadow-xs transition cursor-pointer"
          >
            Try Playground
          </button>
        </div>
      </div>

      {/* Three steps */}
      <div className="space-y-8">
        <div className="text-center space-y-2">
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Up and running in 3 steps</h2>
          <p className="text-slate-500 text-sm">Replace brittle direct integrations with a resilient, explained proxy.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl shadow-xs hover:shadow-md transition space-y-4">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-700 font-bold flex items-center justify-center shadow-xs">
              1
            </div>
            <h3 className="text-lg font-semibold text-slate-900">Plug in your keys</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Store your provider credentials in the encrypted credential vault. Keys are Fernet-encrypted and only the last 4 characters are ever revealed.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl shadow-xs hover:shadow-md transition space-y-4">
            <div className="w-10 h-10 rounded-xl bg-violet-50 border border-violet-100 text-violet-700 font-bold flex items-center justify-center shadow-xs">
              2
            </div>
            <h3 className="text-lg font-semibold text-slate-900">Create an OmniKey</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Generate isolated platform keys with credit limits, RPM caps, allowed routes, and automatic expiration for each team member or project.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl shadow-xs hover:shadow-md transition space-y-4">
            <div className="w-10 h-10 rounded-xl bg-purple-50 border border-purple-100 text-purple-700 font-bold flex items-center justify-center shadow-xs">
              3
            </div>
            <h3 className="text-lg font-semibold text-slate-900">Change your base URL</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Point standard OpenAI or Gemini SDKs to <code className="text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded font-mono text-xs">http://localhost:8000/v1</code>. No custom client libraries required.
            </p>
          </div>
        </div>
      </div>

      {/* Before / After snippet */}
      <div className="space-y-8">
        <div className="text-center space-y-2">
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Before & After</h2>
          <p className="text-slate-500 text-sm">Drop-in replacement for OpenAI and Gemini standard clients.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-6 bg-white border border-rose-200 rounded-2xl space-y-3 shadow-xs">
            <div className="flex items-center justify-between text-rose-700 text-xs font-semibold uppercase tracking-wider">
              <span>Before (Direct Integration)</span>
              <span className="px-2 py-0.5 rounded bg-rose-50 border border-rose-200 text-rose-700">Fragile</span>
            </div>
            <pre className="p-4 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-700 overflow-x-auto leading-relaxed">
              {beforeCode}
            </pre>
          </div>

          <div className="p-6 bg-white border border-indigo-200 rounded-2xl space-y-3 shadow-sm shadow-indigo-100/50">
            <div className="flex items-center justify-between text-indigo-700 text-xs font-semibold uppercase tracking-wider">
              <span>After (OmniKey Gateway)</span>
              <span className="px-2 py-0.5 rounded bg-indigo-50 border border-indigo-200 text-indigo-700 flex items-center space-x-1">
                <CheckCircle2 className="w-3 h-3 text-indigo-600" />
                <span>Resilient</span>
              </span>
            </div>
            <pre className="p-4 bg-slate-900 border border-slate-800 rounded-xl text-xs font-mono text-slate-100 overflow-x-auto leading-relaxed shadow-xs">
              {afterCode}
            </pre>
          </div>
        </div>
      </div>

      {/* Feature Grid */}
      <div className="space-y-8">
        <div className="text-center space-y-2">
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Enterprise control without the friction</h2>
          <p className="text-slate-500 text-sm">Every feature designed with transparency, speed, and safety first.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center">
              <Cpu className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Dynamic Fallback Routing</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Automatic circuit breaker and least-latency failovers. If OpenAI returns a 429 or 500, OmniKey seamlessly routes to Anthropic, Gemini, or Groq.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
              <FileQuestion className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Explainable AI (Why?)</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Every decision, cost calculation, and refusal writes structured facts. Click "Why?" anywhere to see deterministic explanations with zero hallucinations.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Key Vault & Double-Entry Ledger</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Credits are tracked with atomic ledger accounting. Never worry about surprise bills or runaway scripts exceeding quotas.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center">
              <Layers className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Context Sessions & Trimming</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Stateful server-side sessions retain context across fallbacks, with sliding-window token trimming keeping requests within upstream limits.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center">
              <Zap className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Compare & Debate Arenas</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              Test prompts across up to 4 models in parallel or run multi-round AI debates with automated judge rubrics and code-computed rankings.
            </p>
          </div>

          <div className="p-6 bg-white border border-slate-200/80 rounded-2xl space-y-3 shadow-xs hover:shadow-md transition">
            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 border border-purple-100 flex items-center justify-center">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Zero Secret Leakage</h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              No prompt text or secrets are saved in traces unless opted-in. Tenant queries strictly isolate data by organization.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
