'use client'
import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { useSSE, SSEEvent } from '@/lib/sse'
import { api } from '@/lib/api'
import {
  Mic, Lock, Unlock, Play, Pause, RefreshCw, CheckCircle,
  XCircle, Sparkles, Radio, Loader2, AlertTriangle, Volume2,
  GitBranch, Shield, Wand2, ChevronRight,
} from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

type Stage = 'dna' | 'visions' | 'writers_room' | 'lock' | 'audio' | 'done'

type DNA = {
  core_emotion: string; audience_promise: string; protagonist: { name: string; desire: string; fear: string }
  central_conflict: string; symbols: string[]; non_negotiables: string[]; tone: string[]
  creative_freedom: number; locked_fields: string[]
}

type Vision = {
  id: string; title: string; grammar: string; premise: string
  opening_preview: string; emotional_trajectory: string
  cliffhanger_type: string; constitution_score: number; why_it_fits_dna: string
}

type TerminalLine = { agent: string; text: string; type: string; timestamp: number }
type ConstitutionCheck = { rule_number: number; rule: string; passed: boolean; evidence: string; reason?: string; repair?: string }

// ─── Agent colours ────────────────────────────────────────────────────────────
const AGENT_COLOR: Record<string, string> = {
  muse: 'text-purple-400', writer: 'text-blue-400', supervisor: 'text-yellow-400',
  audio_director: 'text-green-400', system: 'text-nolan-muted',
}
const AGENT_LABEL: Record<string, string> = {
  muse: 'MUSE', writer: 'WRITER', supervisor: 'SUPERVISOR',
  audio_director: 'AUDIO DIR', system: 'SYSTEM',
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function SessionPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const sessionId = params.id as string
  const transcript = searchParams.get('transcript') || ''

  const [stage, setStage] = useState<Stage>('dna')
  const [dna, setDna] = useState<DNA | null>(null)
  const [lockedFields, setLockedFields] = useState<Set<string>>(new Set())
  const [visions, setVisions] = useState<Vision[]>([])
  const [selectedVisions, setSelectedVisions] = useState({ opening: '', relationship: '', ending: '' })
  const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([])
  const [tokenBuffer, setTokenBuffer] = useState('')
  const [constitutionChecks, setConstitutionChecks] = useState<ConstitutionCheck[]>([])
  const [constitutionScore, setConstitutionScore] = useState<number | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [reviseInput, setReviseInput] = useState('')
  const [lockDiff, setLockDiff] = useState<any>(null)
  const [isWorking, setIsWorking] = useState(false)
  const [sseUrl, setSseUrl] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)

  // Auto-scroll terminal
  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight
  }, [terminalLines, tokenBuffer])

  // ─── SSE handler ────────────────────────────────────────────────────────────
  const handleSSE = useCallback((e: SSEEvent) => {
    const addLine = (text: string, type = e.type) => {
      setTerminalLines(prev => [...prev, { agent: e.agent, text, type, timestamp: Date.now() }])
    }

    if (e.type === 'token') {
      setTokenBuffer(prev => prev + (typeof e.data === 'string' ? e.data : ''))
      return
    }

    // Flush token buffer as one line
    setTokenBuffer(prev => {
      if (prev) addLine(prev, 'token')
      return ''
    })

    if (e.type === 'status') addLine(String(e.data), 'status')
    if (e.type === 'fallback') addLine(`⚡ ${e.data}`, 'fallback')
    if (e.type === 'error') addLine(`✗ ${e.data}`, 'error')

    if (e.type === 'artifact') {
      const d = e.data
      if (d?.core_emotion) { setDna(d); setStage('visions') }
      if (d?.constitution_score !== undefined) setConstitutionScore(d.constitution_score)
      if (d?.transcript) addLine(`Transcript: "${d.transcript}"`, 'artifact')
      if (d?.url || d?.audio_url) {
        const url = api.audioUrl(sessionId)
        setAudioUrl(url)
        setStage('done')
        setIsWorking(false)
      }
      if (d?.lock_diff) { setLockDiff(d.lock_diff); setStage('done') }
    }

    if (e.type === 'violation') {
      const c = e.data as ConstitutionCheck
      setConstitutionChecks(prev => [...prev.filter(x => x.rule_number !== c.rule_number), c])
      addLine(`✗ RULE ${c.rule_number}: ${c.rule}`, 'violation')
      if (c.repair) addLine(`  ↳ REPAIR: ${c.repair.slice(0, 120)}`, 'repair')
    }

    if (e.type === 'complete') {
      const d = typeof e.data === 'object' ? e.data : {}
      if (d.audio_url || d.status === 'READY') {
        const url = api.audioUrl(sessionId)
        setAudioUrl(url)
        setStage('done')
        setIsWorking(false)
      }
      if (d.visions_count) setStage('writers_room')
      addLine(`✓ ${e.agent.toUpperCase()} complete`, 'complete')
      setSseUrl(null)
    }
  }, [sessionId])

  useSSE(sseUrl, handleSSE)

  // ─── Boot: extract DNA ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!transcript || !sessionId) return
    ;(async () => {
      setIsWorking(true)
      setSseUrl(api.eventsUrl(sessionId))
      addTerminalLine('muse', `Processing: "${transcript.slice(0, 80)}..."`, 'status')
      const dnaResult = await api.extractDNA(sessionId, transcript)
      if (dnaResult?.core_emotion) {
        setDna(dnaResult)
        setStage('visions')
        setIsWorking(false)
      }
    })()
  }, [transcript, sessionId])

  function addTerminalLine(agent: string, text: string, type = 'status') {
    setTerminalLines(prev => [...prev, { agent, text, type, timestamp: Date.now() }])
  }

  // ─── Generate Visions ────────────────────────────────────────────────────────
  async function generateVisions() {
    setIsWorking(true)
    setStage('writers_room')
    setSseUrl(api.eventsUrl(sessionId))
    addTerminalLine('writer', 'Auditioning three directorial visions...', 'status')
    await api.generateVisions(sessionId)
  }

  // ─── Produce ─────────────────────────────────────────────────────────────────
  async function produce() {
    if (!selectedVisions.opening) return
    setIsWorking(true)
    setStage('writers_room')
    setSseUrl(api.eventsUrl(sessionId))
    addTerminalLine('writer', 'Composing production script...', 'status')
    await api.produce(sessionId, {
      primary_vision_id: selectedVisions.opening,
      opening_from: selectedVisions.opening,
      relationship_from: selectedVisions.relationship || selectedVisions.opening,
      ending_from: selectedVisions.ending || selectedVisions.opening,
    })
  }

  // ─── Revise ──────────────────────────────────────────────────────────────────
  async function revise() {
    if (!reviseInput.trim()) return
    setIsWorking(true)
    setLockDiff(null)
    setSseUrl(api.eventsUrl(sessionId))
    addTerminalLine('supervisor', 'Activating Semantic Creative Lock...', 'status')
    await api.revise(sessionId, reviseInput, Array.from(lockedFields))
    setReviseInput('')
  }

  // ─── Toggle Field Lock ────────────────────────────────────────────────────────
  function toggleLock(field: string) {
    setLockedFields(prev => {
      const next = new Set(prev)
      if (next.has(field)) next.delete(field); else next.add(field)
      return next
    })
  }

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen p-4 md:p-6 grid grid-cols-1 lg:grid-cols-3 gap-4 max-w-8xl mx-auto">
      {/* ── LEFT: DNA + Visions ── */}
      <div className="lg:col-span-1 flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center gap-3 py-2">
          <Radio className="w-5 h-5 text-nolan-accent" />
          <span className="font-bold tracking-widest text-sm">NOLAN STUDIO</span>
          {isWorking && <Loader2 className="w-4 h-4 text-nolan-accent animate-spin ml-auto" />}
        </div>

        {/* Creative DNA Card */}
        <AnimatePresence>
          {dna && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="glass rounded-xl p-4"
            >
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-nolan-accent" />
                <span className="text-xs font-bold tracking-widest text-nolan-accent">CREATIVE DNA</span>
              </div>
              <DNAField label="Core Emotion" value={dna.core_emotion} field="core_emotion" locked={lockedFields} onToggle={toggleLock} />
              <DNAField label="Promise" value={dna.audience_promise} field="audience_promise" locked={lockedFields} onToggle={toggleLock} />
              <DNAField label="Protagonist" value={`${dna.protagonist.name} — ${dna.protagonist.desire}`} field="protagonist" locked={lockedFields} onToggle={toggleLock} />
              <DNAField label="Conflict" value={dna.central_conflict} field="central_conflict" locked={lockedFields} onToggle={toggleLock} />
              <DNAField label="Tone" value={dna.tone.join(', ')} field="tone" locked={lockedFields} onToggle={toggleLock} />
              <DNAField label="Must Keep" value={dna.non_negotiables.join(' · ')} field="non_negotiables" locked={lockedFields} onToggle={toggleLock} highlight />
              <div className="mt-3 flex gap-2 flex-wrap">
                {dna.symbols.map(s => (
                  <span key={s} className="text-xs px-2 py-0.5 bg-nolan-border rounded-full text-nolan-muted">{s}</span>
                ))}
              </div>
              {stage === 'visions' && (
                <motion.button
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  onClick={generateVisions}
                  disabled={isWorking}
                  className="mt-4 w-full py-2 bg-nolan-accent text-white rounded-lg text-sm hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  <GitBranch className="w-4 h-4" /> Audition Three Visions
                </motion.button>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Vision Cards */}
        <AnimatePresence>
          {visions.length > 0 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-bold tracking-widest text-blue-400">DIRECTORIAL VISIONS</span>
              </div>
              {visions.map(v => (
                <VisionCard
                  key={v.id}
                  vision={v}
                  selected={selectedVisions.opening === v.id}
                  onSelect={() => setSelectedVisions(prev => ({
                    opening: v.id,
                    relationship: prev.relationship || v.id,
                    ending: prev.ending || v.id,
                  }))}
                />
              ))}
              {selectedVisions.opening && (
                <button
                  onClick={produce}
                  disabled={isWorking}
                  className="w-full py-2 bg-nolan-accent text-white rounded-lg text-sm hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  <Wand2 className="w-4 h-4" /> Produce Pilot
                </button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── CENTRE: Writers' Room Terminal ── */}
      <div className="lg:col-span-1 flex flex-col gap-4">
        <div className="glass rounded-xl flex flex-col h-full" style={{ minHeight: '60vh' }}>
          <div className="flex items-center gap-2 px-4 py-3 border-b border-nolan-border">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500" />
              <span className="w-3 h-3 rounded-full bg-yellow-500" />
              <span className="w-3 h-3 rounded-full bg-green-500" />
            </div>
            <span className="text-xs text-nolan-muted ml-2 tracking-widest">WRITERS' ROOM</span>
            {isWorking && <span className="ml-auto text-xs text-nolan-accent animate-pulse">● LIVE</span>}
          </div>

          <div
            ref={terminalRef}
            className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1"
            style={{ maxHeight: '65vh' }}
          >
            {terminalLines.map((line, i) => (
              <TerminalLineView key={i} line={line} />
            ))}
            {tokenBuffer && (
              <span className={`${AGENT_COLOR['muse']} opacity-80`}>
                {tokenBuffer}<span className="cursor" />
              </span>
            )}
            {terminalLines.length === 0 && !isWorking && (
              <p className="text-nolan-muted">Waiting for imagination...</p>
            )}
          </div>
        </div>

        {/* Constitution Checks */}
        <AnimatePresence>
          {constitutionChecks.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-yellow-400" />
                  <span className="text-xs font-bold tracking-widest text-yellow-400">STORY CONSTITUTION</span>
                </div>
                {constitutionScore !== null && (
                  <span className={`text-sm font-bold ${constitutionScore >= 80 ? 'text-nolan-green' : 'text-nolan-red'}`}>
                    {constitutionScore}/100
                  </span>
                )}
              </div>
              <div className="space-y-2">
                {constitutionChecks.map(c => (
                  <ConstitutionCheckView key={c.rule_number} check={c} />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── RIGHT: Lock + Audio ── */}
      <div className="lg:col-span-1 flex flex-col gap-4">
        {/* Semantic Creative Lock */}
        <AnimatePresence>
          {stage !== 'dna' && (
            <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="glass rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Lock className="w-4 h-4 text-nolan-gold" />
                <span className="text-xs font-bold tracking-widest text-nolan-gold">SEMANTIC CREATIVE LOCK</span>
              </div>
              <p className="text-nolan-muted text-xs mb-3">
                Say what to change. Locked fields above are preserved.
              </p>
              <textarea
                value={reviseInput}
                onChange={e => setReviseInput(e.target.value)}
                placeholder="Make the brother dangerous instead of protective, but preserve the final reveal."
                rows={3}
                className="w-full bg-nolan-surface border border-nolan-border rounded-lg p-3 text-xs text-nolan-text resize-none focus:outline-none focus:border-nolan-gold transition-colors"
              />
              <button
                onClick={revise}
                disabled={isWorking || !reviseInput.trim()}
                className="mt-2 w-full py-2 border border-nolan-gold text-nolan-gold rounded-lg text-xs hover:bg-nolan-gold hover:text-black disabled:opacity-40 transition-all flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-3 h-3" /> Apply Lock
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Lock Diff */}
        <AnimatePresence>
          {lockDiff && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="glass rounded-xl p-4">
              <p className="text-xs font-bold text-nolan-gold mb-2 tracking-widest">CREATIVE LOCK ACTIVE</p>
              <div className="space-y-1 text-xs">
                <p className="text-nolan-muted">Changed:</p>
                {(lockDiff.affected_scene_ids || []).map((s: string) => (
                  <p key={s} className="text-nolan-red pl-2">↳ {s}</p>
                ))}
                <p className="text-nolan-muted mt-2">Preserved:</p>
                {(lockDiff.preserved_elements || []).map((s: string) => (
                  <p key={s} className="text-nolan-green pl-2">✓ {s}</p>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Audio Player */}
        <AnimatePresence>
          {audioUrl && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass rounded-xl p-5 border border-nolan-accent/40"
              style={{ boxShadow: '0 0 30px rgba(108,71,255,0.15)' }}
            >
              <div className="flex items-center gap-2 mb-4">
                <Volume2 className="w-4 h-4 text-nolan-accent" />
                <span className="text-xs font-bold tracking-widest text-nolan-accent">CINEMATIC PILOT</span>
              </div>
              <audio
                ref={audioRef}
                src={audioUrl}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                className="hidden"
              />
              {/* Waveform visualizer (CSS only) */}
              <div className="flex items-center justify-center gap-1 h-12 mb-4">
                {Array.from({ length: 24 }).map((_, i) => (
                  <motion.div
                    key={i}
                    className="w-1 bg-nolan-accent rounded-full"
                    animate={playing
                      ? { height: [4, Math.random() * 36 + 8, 4] }
                      : { height: 4 }
                    }
                    transition={{ duration: 0.5 + Math.random() * 0.5, repeat: Infinity, delay: i * 0.05 }}
                  />
                ))}
              </div>
              <button
                onClick={() => playing ? audioRef.current?.pause() : audioRef.current?.play()}
                className="w-full py-3 bg-nolan-accent text-white rounded-xl text-sm font-bold tracking-wider hover:opacity-90 flex items-center justify-center gap-3 transition-all"
                style={{ boxShadow: playing ? '0 0 20px rgba(108,71,255,0.5)' : undefined }}
              >
                {playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                {playing ? 'PAUSE' : 'PLAY PILOT'}
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Stats */}
        {stage === 'done' && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="glass rounded-xl p-4 text-xs text-nolan-muted space-y-1">
            <p className="text-nolan-green font-bold mb-2">✓ Pilot Production Complete</p>
            <p>→ 1 raw idea compiled</p>
            <p>→ 3 directorial visions auditioned</p>
            <p>→ 8 story rules evaluated</p>
            <p>→ Script + characters + audio generated</p>
            <p className="pt-2 text-nolan-muted italic">
              "Other AI generates content. Nolan protects imagination."
            </p>
          </motion.div>
        )}
      </div>
    </div>
  )
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function DNAField({ label, value, field, locked, onToggle, highlight }:
  { label: string; value: string; field: string; locked: Set<string>; onToggle: (f: string) => void; highlight?: boolean }) {
  const isLocked = locked.has(field)
  return (
    <div className={`flex items-start gap-2 py-1.5 border-b border-nolan-border/30 group ${highlight ? 'text-nolan-gold' : ''}`}>
      <button onClick={() => onToggle(field)} className="mt-0.5 flex-shrink-0">
        {isLocked
          ? <Lock className="w-3 h-3 text-nolan-gold" />
          : <Unlock className="w-3 h-3 text-nolan-muted group-hover:text-nolan-accent transition-colors" />}
      </button>
      <div className="min-w-0">
        <p className="text-nolan-muted text-[10px] uppercase tracking-widest">{label}</p>
        <p className="text-xs text-nolan-text truncate">{value}</p>
      </div>
    </div>
  )
}

function VisionCard({ vision, selected, onSelect }:
  { vision: Vision; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const scoreColor = vision.constitution_score >= 85 ? 'text-nolan-green' : vision.constitution_score >= 70 ? 'text-yellow-400' : 'text-nolan-red'

  return (
    <motion.div
      layout
      onClick={onSelect}
      className={`glass glass-hover rounded-xl p-3 cursor-pointer border transition-all ${
        selected ? 'border-nolan-accent shadow-[0_0_15px_rgba(108,71,255,0.3)]' : 'border-transparent'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {selected && <CheckCircle className="w-3 h-3 text-nolan-accent flex-shrink-0" />}
          <span className="text-xs font-bold text-white">{vision.title}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold ${scoreColor}`}>{vision.constitution_score}</span>
          <button onClick={e => { e.stopPropagation(); setOpen(!open) }} className="text-nolan-muted hover:text-white">
            <ChevronRight className={`w-3 h-3 transition-transform ${open ? 'rotate-90' : ''}`} />
          </button>
        </div>
      </div>
      <p className="text-nolan-muted text-[11px] mt-1">{vision.premise.slice(0, 80)}...</p>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
            <pre className="text-[10px] text-blue-300 mt-2 whitespace-pre-wrap font-mono">{vision.opening_preview}</pre>
            <p className="text-[10px] text-nolan-muted mt-1">↳ {vision.cliffhanger_type}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function TerminalLineView({ line }: { line: TerminalLine }) {
  const color = AGENT_COLOR[line.agent] || 'text-nolan-text'
  const label = AGENT_LABEL[line.agent] || line.agent.toUpperCase()
  const textColor = line.type === 'violation' ? 'text-nolan-red'
    : line.type === 'repair' ? 'text-nolan-green'
    : line.type === 'fallback' ? 'text-nolan-gold'
    : line.type === 'complete' ? 'text-nolan-green'
    : 'text-nolan-text'

  return (
    <div className="flex gap-2 text-xs">
      <span className={`${color} flex-shrink-0 w-16 opacity-70`}>[{label}]</span>
      <span className={textColor}>{line.text}</span>
    </div>
  )
}

function ConstitutionCheckView({ check }: { check: ConstitutionCheck }) {
  const [open, setOpen] = useState(!check.passed)
  return (
    <div className={`rounded-lg px-3 py-2 ${check.passed ? 'bg-nolan-green/5' : 'bg-nolan-red/10 border border-nolan-red/20'}`}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen(!open)}>
        {check.passed
          ? <CheckCircle className="w-3 h-3 text-nolan-green flex-shrink-0" />
          : <XCircle className="w-3 h-3 text-nolan-red flex-shrink-0" />}
        <span className="text-[11px] text-nolan-text flex-1">{check.rule}</span>
      </div>
      <AnimatePresence>
        {open && !check.passed && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}>
            <p className="text-[10px] text-nolan-muted mt-1 pl-5">Evidence: {check.evidence?.slice(0, 100)}</p>
            {check.repair && <p className="text-[10px] text-nolan-green mt-1 pl-5">↳ {check.repair.slice(0, 120)}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
