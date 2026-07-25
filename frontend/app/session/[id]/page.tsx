'use client'
import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { useSSE } from '@/lib/sse'
import { api } from '@/lib/api'
import {
  Mic, Lock, Unlock, Play, Pause, CheckCircle, XCircle,
  Sparkles, Radio, Loader2, Volume2, GitBranch, Shield,
  Wand2, ChevronRight, ChevronDown, ArrowRight, RefreshCw, Zap, Film, Upload,
} from 'lucide-react'

// ─── Step definition ──────────────────────────────────────────────────────────
const STEPS = [
  { id: 'dna',         label: 'Your story',      icon: Sparkles  },
  { id: 'visions',     label: 'Choose a feeling',icon: GitBranch },
  { id: 'production',  label: 'Make it real',    icon: Shield    },
  { id: 'audio',       label: 'Your episode',    icon: Volume2   },
]

type Step = 'dna' | 'visions' | 'production' | 'audio'

type DNA = {
  core_emotion: string; audience_promise: string
  protagonist: { name: string; desire: string; fear: string }
  central_conflict: string; symbols: string[]
  non_negotiables: string[]; tone: string[]
  genre?: string[]; story_references?: string[]
  characters?: Array<{ name: string; role: string; relationship_to_protagonist: string; want: string; secret_or_tension: string }>
  creative_freedom: number; locked_fields: string[]
}

type Vision = {
  id: string; title: string; grammar: string; premise: string
  opening_preview: string; emotional_trajectory: string
  cliffhanger_type: string; constitution_score: number; why_it_fits_dna: string
}

type TermLine = { agent: string; text: string; type: string }
type Check = { rule_number: number; rule: string; passed: boolean; evidence: string; reason?: string; repair?: string }

const AGENT_COLOR: Record<string, string> = {
  muse: 'text-purple-400', writer: 'text-blue-400',
  supervisor: 'text-yellow-400', audio_director: 'text-green-400',
}

export default function SessionPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const sessionId = params.id as string
  const transcript = searchParams.get('transcript') || ''

  const [step, setStep] = useState<Step>('dna')
  const [busy, setBusy] = useState(false)
  const [sseUrl, setSseUrl] = useState<string | null>(null)
  const [transcriptDraft, setTranscriptDraft] = useState(transcript)
  const [storyApproved, setStoryApproved] = useState(false)

  const [dna, setDna] = useState<DNA | null>(null)
  const [lockedFields, setLockedFields] = useState<Set<string>>(new Set())

  const [visions, setVisions] = useState<Vision[]>([])
  const [selectedVision, setSelectedVision] = useState<string>('')

  const [termLines, setTermLines] = useState<TermLine[]>([])
  const [tokenBuf, setTokenBuf] = useState('')

  const [checks, setChecks] = useState<Check[]>([])
  const [score, setScore] = useState<number | null>(null)

  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)

  const [revise, setRevise] = useState('')
  const [lockDiff, setLockDiff] = useState<any>(null)
  const [portraitFile, setPortraitFile] = useState<File | null>(null)
  const [liveVideoFile, setLiveVideoFile] = useState<File | null>(null)
  const [visualPlan, setVisualPlan] = useState<any>(null)

  const audioRef = useRef<HTMLAudioElement>(null)
  const termRef  = useRef<HTMLDivElement>(null)

  // Auto-scroll terminal
  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
  }, [termLines, tokenBuf])

  const pushLine = useCallback((agent: string, text: string, type = 'status') => {
    setTermLines(prev => [...prev, { agent, text, type }])
  }, [])

  // ─── SSE handler ─────────────────────────────────────────────────────────────
  const handleSSE = useCallback((e: any) => {
    if (e.type === 'token') {
      setTokenBuf(prev => prev + (typeof e.data === 'string' ? e.data : ''))
      return
    }

    // Flush token buffer
    setTokenBuf(prev => {
      if (prev.trim()) pushLine(e.agent, prev, 'token')
      return ''
    })

    if (e.type === 'status')   pushLine(e.agent, String(e.data), 'status')
    if (e.type === 'fallback') pushLine(e.agent, `⚡ ${e.data}`, 'fallback')
    if (e.type === 'error')    pushLine(e.agent, `✗ ${e.data}`, 'error')

    if (e.type === 'violation') {
      const c = e.data as Check
      setChecks(prev => [...prev.filter(x => x.rule_number !== c.rule_number), c])
    }

    if (e.type === 'artifact') {
      const d = e.data
      // DNA arrived
      if (d?.core_emotion) { setDna(d); setStep('visions'); setBusy(false) }
      // Constitution score
      if (d?.score !== undefined) setScore(d.score)
      // Creative lock diff
      if (d?.lock_diff) {
        setLockDiff(d.lock_diff)
        pushLine(e.agent, '✓ Semantic Creative Lock applied', 'complete')
      }
    }

    if (e.type === 'complete') {
      const d = typeof e.data === 'object' ? e.data : {}
      if (d.visions_count) setStep('production')
      if (d.status === 'READY' || d.audio_url) {
        setAudioUrl(api.audioUrl(sessionId))
        setStep('audio')
      }
      setBusy(false)
      setSseUrl(null)
    }
  }, [sessionId, pushLine])

  useSSE(sseUrl, handleSSE)

  // ─── Boot: extract DNA on load ──────────────────────────────────────────────
  useEffect(() => {
    if (!storyApproved || !transcriptDraft.trim() || !sessionId) return
    ;(async () => {
      setBusy(true)
      setSseUrl(api.eventsUrl(sessionId))
      pushLine('muse', `Listening for the heart of your story…`)
      const result = await api.extractDNA(sessionId, transcriptDraft)
      if (result?.core_emotion) { setDna(result); setStep('visions'); setBusy(false) }
    })()
  }, [storyApproved, transcriptDraft, sessionId, pushLine])

  // ─── Actions ──────────────────────────────────────────────────────────────────
  async function doGenerateVisions() {
    if (!dna) return
    setBusy(true)
    setStep('visions')
    setSseUrl(api.eventsUrl(sessionId))
    pushLine('writer', 'Finding three ways your story could feel…')
    const res = await api.generateVisions(sessionId)
    // Visions arrive via SSE artifacts
    // Poll session as fallback
    setTimeout(async () => {
      const s = await api.getSession(sessionId)
      if (s.visions?.length) { setVisions(s.visions); setBusy(false) }
    }, 3000)
  }

  async function doProduce() {
    if (!selectedVision) return
    setBusy(true)
    setStep('production')
    setSseUrl(api.eventsUrl(sessionId))
    pushLine('writer', 'Turning your chosen story into an episode…')
    await api.produce(sessionId, {
      primary_vision_id: selectedVision,
      opening_from: selectedVision,
      relationship_from: selectedVision,
      ending_from: selectedVision,
    })
  }

  async function doRevise() {
    if (!revise.trim()) return
    setBusy(true)
    setLockDiff(null)
    setSseUrl(api.eventsUrl(sessionId))
    pushLine('supervisor', `Locking: "${revise.slice(0, 60)}"`)
    await api.revise(sessionId, revise, Array.from(lockedFields))
    setRevise('')
  }

  async function doPlanVisualEpisode() {
    setBusy(true)
    try {
      if (portraitFile) await api.uploadVisualAsset(sessionId, 'portrait', portraitFile)
      if (liveVideoFile) await api.uploadVisualAsset(sessionId, 'live_video', liveVideoFile)
      setVisualPlan(await api.planVisualEpisode(sessionId, Boolean(portraitFile), Boolean(liveVideoFile)))
    } finally { setBusy(false) }
  }

  function toggleLock(field: string) {
    setLockedFields(prev => {
      const n = new Set(prev)
      n.has(field) ? n.delete(field) : n.add(field)
      return n
    })
  }

  const currentStepIdx = STEPS.findIndex(s => s.id === step)

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Top Bar ── */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-nolan-border/50">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-nolan-accent" />
          <span className="font-bold text-sm tracking-wider">NOLAN <span className="text-nolan-muted font-normal">/ dream studio</span></span>
        </div>

        {/* Step progress */}
        <div className="flex items-center gap-2">
          {STEPS.map((s, i) => {
            const done = i < currentStepIdx
            const active = i === currentStepIdx
            return (
              <span key={s.id} className="flex items-center gap-2">
                <span className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full transition-all ${
                  done   ? 'text-nolan-green bg-nolan-green/10' :
                  active ? 'text-white bg-nolan-accent' :
                           'text-nolan-muted'
                }`}>
                  {done ? <CheckCircle className="w-3 h-3" /> : <s.icon className="w-3 h-3" />}
                  <span className="hidden sm:inline">{s.label}</span>
                </span>
                {i < STEPS.length - 1 && <ArrowRight className="w-3 h-3 text-nolan-border" />}
              </span>
            )
          })}
        </div>

        {busy && <div className="flex items-center gap-2 text-xs text-nolan-accent">
          <Loader2 className="w-3 h-3 animate-spin" /> Working...
        </div>}
      </header>

      {/* ── Body ── */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 gap-0 overflow-hidden">

        {/* LEFT — Main content (3 cols) */}
        <div className="lg:col-span-3 p-5 flex flex-col gap-5 overflow-y-auto">

          {!dna && !busy && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass rounded-2xl p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-nolan-accent">Nolan heard this</p>
              <h1 className="text-2xl font-bold text-white mt-2">Is this your story?</h1>
              <p className="text-sm text-nolan-muted mt-1">Edit anything before Nolan creates the people, world, genre, and episode.</p>
              <textarea value={transcriptDraft} onChange={e => setTranscriptDraft(e.target.value)} rows={6}
                className="w-full mt-4 bg-black/20 border border-nolan-border rounded-xl p-4 text-sm text-white resize-none focus:outline-none focus:border-nolan-accent" />
              <button onClick={() => setStoryApproved(true)} disabled={!transcriptDraft.trim()}
                className="w-full mt-3 py-3 bg-nolan-accent text-white rounded-xl font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-40">
                <Sparkles className="w-4 h-4" /> Yes — build my story
              </button>
            </motion.section>
          )}

          {!dna && busy && <div className="glass rounded-2xl p-8 text-center"><Loader2 className="w-7 h-7 text-nolan-accent animate-spin mx-auto" /><p className="text-white mt-3">Nolan is finding the people and world inside your story…</p></div>}

          {/* ── STEP 1: Creative DNA ── */}
          {dna && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Sparkles className="w-4 h-4 text-purple-400" />} label="Nolan heard your story" badge="You can change this later" />
              <div className="glass rounded-2xl p-5 mt-2 overflow-hidden relative">
                <div className="absolute -right-12 -top-12 w-40 h-40 bg-nolan-accent/20 blur-3xl rounded-full" />
                <p className="text-[11px] uppercase tracking-[0.2em] text-nolan-accent mb-2">Your main character</p>
                <h1 className="text-3xl font-bold text-white">{dna.protagonist.name}</h1>
                <p className="text-nolan-muted text-sm mt-1">Wants to {dna.protagonist.desire} — but fears {dna.protagonist.fear}.</p>
                <div className="flex gap-2 flex-wrap mt-3">{(dna.genre || []).map((g: string) => <Tag key={g} text={g} color="purple" />)}{(dna.story_references || []).map((r: string) => <Tag key={r} text={`inspired by ${r}`} color="default" />)}</div>
                <div className="grid sm:grid-cols-2 gap-3 mt-5">
                  <div className="rounded-xl bg-black/20 p-3"><p className="text-[10px] uppercase tracking-widest text-nolan-muted">The feeling</p><p className="text-sm text-white mt-1">{dna.core_emotion}</p></div>
                  <div className="rounded-xl bg-black/20 p-3"><p className="text-[10px] uppercase tracking-widest text-nolan-muted">The problem</p><p className="text-sm text-white mt-1">{dna.central_conflict}</p></div>
                </div>
                {(dna.characters || []).length > 1 && <div className="mt-4"><p className="text-[10px] uppercase tracking-widest text-nolan-muted mb-2">The people in this episode</p><div className="grid sm:grid-cols-2 gap-2">{(dna.characters || []).filter((c: any) => c.name !== dna.protagonist.name).map((c: any) => <div key={c.name} className="rounded-xl bg-black/20 p-3"><p className="text-sm text-white">{c.name} <span className="text-nolan-muted">· {c.role}</span></p><p className="text-[11px] text-nolan-muted mt-1">{c.relationship_to_protagonist} — {c.secret_or_tension}</p></div>)}</div></div>}
                <p className="text-xs text-nolan-gold mt-4">We will protect: {dna.non_negotiables.join(' · ')}</p>
                <div className="flex gap-2 flex-wrap pt-3">{dna.tone.map(t => <Tag key={t} text={t} color="purple" />)}{dna.symbols.map(s => <Tag key={s} text={s} color="default" />)}</div>
              </div>
              {step === 'visions' && visions.length === 0 && (
                <button onClick={doGenerateVisions} disabled={busy}
                  className="mt-3 w-full py-2.5 bg-nolan-accent text-white rounded-xl text-sm font-semibold hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2">
                  <GitBranch className="w-4 h-4" /> Show me three ways this could feel
                </button>
              )}
            </motion.section>
          )}

          {/* ── STEP 2: Visions ── */}
          {visions.length > 0 && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<GitBranch className="w-4 h-4 text-blue-400" />} label="Choose the feeling" badge="Pick the version you would play first" />
              <div className="space-y-3 mt-2">
                {visions.map(v => (
                  <VisionCard key={v.id} vision={v} selected={selectedVision === v.id}
                    onSelect={() => setSelectedVision(v.id)} />
                ))}
              </div>
              {selectedVision && (
                <button onClick={doProduce} disabled={busy}
                  className="mt-3 w-full py-2.5 bg-nolan-accent text-white rounded-xl text-sm font-semibold hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2">
                  <Wand2 className="w-4 h-4" /> Make my first episode
                </button>
              )}
            </motion.section>
          )}

          {/* ── STEP 3: Constitution ── */}
          {checks.length > 0 && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Shield className="w-4 h-4 text-yellow-400" />}
                label="Your story is ready" badge={score !== null ? `${score}/100 story-ready` : undefined} />
              <div className="glass rounded-xl p-4 space-y-2 mt-2">
                {checks.sort((a,b) => a.rule_number - b.rule_number).map(c => (
                  <ConstitutionRow key={c.rule_number} check={c} />
                ))}
              </div>
            </motion.section>
          )}

          {/* ── STEP 4: Audio Pilot ── */}
          {audioUrl && (
            <motion.section initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}>
              <SectionHeader icon={<Volume2 className="w-4 h-4 text-nolan-accent" />} label="Cinematic Audio Pilot" />
              <div className="glass rounded-xl p-5 mt-2 border border-nolan-accent/30"
                style={{ boxShadow: '0 0 30px rgba(108,71,255,0.1)' }}>
                <audio ref={audioRef} src={audioUrl}
                  onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                  onEnded={() => setPlaying(false)} className="hidden" />
                {/* Waveform */}
                <div className="flex items-center justify-center gap-0.5 h-10 mb-4">
                  {Array.from({ length: 32 }).map((_, i) => (
                    <motion.div key={i} className="w-1 rounded-full bg-nolan-accent"
                      animate={playing ? { height: [3, 6 + Math.random() * 26, 3] } : { height: 3 }}
                      transition={{ duration: 0.4 + Math.random() * 0.4, repeat: Infinity, delay: i * 0.04 }} />
                  ))}
                </div>
                <button onClick={() => playing ? audioRef.current?.pause() : audioRef.current?.play()}
                  className="w-full py-3 bg-nolan-accent text-white rounded-xl font-bold tracking-wider text-sm flex items-center justify-center gap-3">
                  {playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                  {playing ? 'Pause' : 'Play Pilot'}
                </button>
              </div>
              <div className="glass rounded-xl p-4 mt-3 border border-pink-400/25">
                <div className="flex items-center gap-2 mb-2"><Film className="w-4 h-4 text-pink-300" /><span className="text-xs font-bold tracking-wider text-pink-200">VISUAL EPISODE</span></div>
                <p className="text-[11px] text-nolan-muted mb-3">Plan a 90-second vertical edit with your optional portrait and auditorium clip.</p>
                <input className="block w-full text-[10px] mb-2" type="file" accept="image/*" onChange={e => setPortraitFile(e.target.files?.[0] || null)} />
                <input className="block w-full text-[10px] mb-3" type="file" accept="video/*" onChange={e => setLiveVideoFile(e.target.files?.[0] || null)} />
                <button onClick={doPlanVisualEpisode} disabled={busy} className="w-full py-2 rounded-lg border border-pink-300/50 text-pink-200 text-xs flex justify-center gap-2"><Upload className="w-3 h-3" />Plan Visual Episode</button>
                {visualPlan && <p className="text-[10px] text-pink-200 mt-2">✓ {visualPlan.beats?.length} visual beats planned for {visualPlan.target_duration_seconds}s</p>}
              </div>
              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 mt-3">
                {[
                  ['1 raw idea', 'compiled'],
                  ['3 visions', 'auditioned'],
                  ['8 rules', 'evaluated'],
                  ['1 revision', 'with lock'],
                ].map(([n, l]) => (
                  <div key={n} className="glass rounded-xl p-3 text-center">
                    <p className="text-nolan-accent font-bold text-lg">{n}</p>
                    <p className="text-nolan-muted text-xs">{l}</p>
                  </div>
                ))}
              </div>
            </motion.section>
          )}
        </div>

        {/* Advanced controls stay out of the first-time creator flow. */}
        <details className="lg:col-span-2 border-l border-nolan-border/50 group">
          <summary className="cursor-pointer list-none px-5 py-4 text-xs text-nolan-muted hover:text-white flex items-center gap-2">
            <ChevronRight className="w-4 h-4 transition-transform group-open:rotate-90" />
            Behind the scenes — refine the story or see Nolan at work
          </summary>
          <div className="flex flex-col border-t border-nolan-border/30">

          {/* Terminal */}
          <div className="flex-1 flex flex-col" style={{ minHeight: 0 }}>
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-nolan-border/50">
              <span className="flex gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" />
                <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" />
                <span className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
              </span>
              <span className="text-xs text-nolan-muted ml-1 tracking-widest">BEHIND THE SCENES</span>
              {busy && <span className="ml-auto flex items-center gap-1 text-xs text-nolan-accent">
                <span className="w-1.5 h-1.5 rounded-full bg-nolan-accent animate-pulse" /> LIVE
              </span>}
            </div>
            <div ref={termRef} className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-0.5 bg-black/20"
              style={{ maxHeight: '45vh' }}>
              {termLines.map((l, i) => <TermLine key={i} line={l} />)}
              {tokenBuf && (
                <span className="text-nolan-muted opacity-80">
                  {tokenBuf}<span className="cursor" />
                </span>
              )}
              {termLines.length === 0 && (
                <p className="text-nolan-muted/50">Waiting for your idea...</p>
              )}
            </div>
          </div>

          {/* Semantic Creative Lock panel */}
          <div className="border-t border-nolan-border/50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Lock className="w-4 h-4 text-nolan-gold" />
              <span className="text-xs font-bold text-nolan-gold tracking-wider">SEMANTIC CREATIVE LOCK</span>
            </div>
            <p className="text-nolan-muted text-xs mb-2">
              Want to change the story? Nolan keeps the parts you love and rewrites the rest.
            </p>
            <textarea
              value={revise}
              onChange={e => setRevise(e.target.value)}
              placeholder="Try: make it sadder, but keep Maya's final choice."
              rows={2}
              className="w-full bg-nolan-surface border border-nolan-border/70 rounded-lg p-2.5 text-xs text-nolan-text placeholder:text-nolan-muted/40 resize-none focus:outline-none focus:border-nolan-gold transition-colors"
            />
            <button onClick={doRevise} disabled={busy || !revise.trim()}
              className="mt-2 w-full py-2 border border-nolan-gold/60 text-nolan-gold rounded-lg text-xs font-semibold hover:bg-nolan-gold/10 disabled:opacity-30 transition-all flex items-center justify-center gap-2">
              <RefreshCw className="w-3 h-3" /> Update my story
            </button>

            {/* Lock diff result */}
            <AnimatePresence>
              {lockDiff && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                  className="mt-3 text-xs space-y-1 border-t border-nolan-border/30 pt-3">
                  <p className="font-bold text-nolan-gold">Lock Applied</p>
                  {(lockDiff.affected_scene_ids || []).map((s: string) => (
                    <p key={s} className="text-nolan-red pl-2">↳ changed: {s}</p>
                  ))}
                  {(lockDiff.preserved_elements || []).map((s: string) => (
                    <p key={s} className="text-nolan-green pl-2">✓ kept: {s}</p>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          </div>
        </details>
      </div>
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SectionHeader({ icon, label, badge }: { icon: React.ReactNode; label: string; badge?: string }) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <span className="text-sm font-bold tracking-wide text-white">{label}</span>
      {badge && <span className="ml-auto text-xs text-nolan-muted bg-nolan-surface px-2 py-0.5 rounded-full">{badge}</span>}
    </div>
  )
}

function DNARow({ label, value, field, locked, onToggle, highlight }:
  { label: string; value: string; field: string; locked: Set<string>; onToggle: (f: string) => void; highlight?: boolean }) {
  const isLocked = locked.has(field)
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-nolan-border/20 group">
      <button onClick={() => onToggle(field)} className="mt-0.5 flex-shrink-0" title={isLocked ? 'Click to unlock' : 'Click to lock'}>
        {isLocked
          ? <Lock className="w-3.5 h-3.5 text-nolan-gold" />
          : <Unlock className="w-3.5 h-3.5 text-nolan-muted group-hover:text-nolan-accent transition-colors" />}
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-nolan-muted text-[10px] uppercase tracking-widest">{label}</p>
        <p className={`text-xs ${highlight ? 'text-nolan-gold' : 'text-nolan-text'}`}>{value}</p>
      </div>
    </div>
  )
}

function Tag({ text, color }: { text: string; color: 'purple' | 'default' }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full ${
      color === 'purple' ? 'bg-purple-500/10 text-purple-400' : 'bg-nolan-border text-nolan-muted'
    }`}>{text}</span>
  )
}

function VisionCard({ vision, selected, onSelect }:
  { vision: Vision; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const scoreColor = vision.constitution_score >= 85 ? 'text-nolan-green' :
                     vision.constitution_score >= 70 ? 'text-yellow-400' : 'text-nolan-red'
  return (
    <motion.div layout onClick={onSelect}
      className={`glass rounded-xl p-3.5 cursor-pointer transition-all ${
        selected ? 'border border-nolan-accent shadow-[0_0_20px_rgba(108,71,255,0.2)]' : 'border border-transparent hover:border-nolan-border'
      }`}
    >
      <div className="flex items-start gap-2">
        <div className={`w-4 h-4 rounded-full flex-shrink-0 mt-0.5 flex items-center justify-center border-2 transition-all ${
          selected ? 'border-nolan-accent bg-nolan-accent' : 'border-nolan-border'
        }`}>
          {selected && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-white">{vision.title}</p>
            <span className={`text-xs font-bold flex-shrink-0 ${scoreColor}`}>{vision.constitution_score}/100</span>
          </div>
          <p className="text-nolan-muted text-xs mt-0.5">{vision.premise.slice(0, 85)}...</p>
        </div>
      </div>

      {/* Expand preview */}
      <button onClick={e => { e.stopPropagation(); setOpen(!open) }}
        className="mt-2 w-full text-left text-xs text-nolan-muted/60 hover:text-nolan-muted flex items-center gap-1">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {open ? 'Hide preview' : 'Show opening preview'}
      </button>

      <AnimatePresence>
        {open && (
          <motion.pre initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="text-[11px] text-blue-300 mt-2 whitespace-pre-wrap font-mono bg-black/30 rounded-lg p-2 overflow-hidden">
            {vision.opening_preview}
          </motion.pre>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function ConstitutionRow({ check }: { check: Check }) {
  const [open, setOpen] = useState(!check.passed)
  return (
    <div className={`rounded-lg px-3 py-2 transition-all ${check.passed ? 'bg-nolan-green/5' : 'bg-nolan-red/8 border border-nolan-red/20'}`}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen(!open)}>
        {check.passed
          ? <CheckCircle className="w-3.5 h-3.5 text-nolan-green flex-shrink-0" />
          : <XCircle className="w-3.5 h-3.5 text-nolan-red flex-shrink-0" />}
        <span className="text-xs text-nolan-text flex-1">Rule {check.rule_number}: {check.rule}</span>
        {!check.passed && <ChevronDown className={`w-3 h-3 text-nolan-muted transition-transform ${open ? '' : '-rotate-90'}`} />}
      </div>
      <AnimatePresence>
        {open && !check.passed && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}>
            {check.evidence && <p className="text-[11px] text-nolan-muted mt-1 pl-5">Evidence: {check.evidence.slice(0, 120)}</p>}
            {check.repair  && <p className="text-[11px] text-nolan-green mt-1 pl-5">↳ Repair: {check.repair.slice(0, 120)}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function TermLine({ line }: { line: TermLine }) {
  const agentColor = AGENT_COLOR[line.agent] || 'text-nolan-muted'
  const textColor  = line.type === 'violation' ? 'text-nolan-red'
                   : line.type === 'repair'    ? 'text-nolan-green'
                   : line.type === 'fallback'  ? 'text-nolan-gold'
                   : line.type === 'complete'  ? 'text-nolan-green'
                   : line.type === 'error'     ? 'text-nolan-red'
                   : 'text-nolan-text/80'
  const label = line.agent.replace('_', ' ').toUpperCase().slice(0, 8)
  return (
    <div className="flex gap-2 leading-relaxed">
      <span className={`${agentColor} opacity-60 flex-shrink-0 text-[10px] w-14`}>[{label}]</span>
      <span className={`${textColor} text-[11px] break-words flex-1`}>{line.text}</span>
    </div>
  )
}
