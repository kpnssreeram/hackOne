'use client'
import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Mic, MicOff, Type, Loader2, Sparkles, Radio, ArrowRight, Zap } from 'lucide-react'
import { api } from '@/lib/api'

const EXAMPLES = [
  "I dreamed the entire world forgot me, but my dead brother kept calling my phone.",
  "A food delivery driver gets an order from his missing sister's old address.",
  "Two strangers discover they've been having the same dream for a year.",
  "A woman finds her own obituary — dated three days from now.",
]

export default function Home() {
  const router = useRouter()
  const [mode, setMode] = useState<'voice' | 'text'>('text')
  const [recording, setRecording] = useState(false)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [textInput, setTextInput] = useState('')
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const loadingRef = useRef(false)   // synchronous double-click guard

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      chunksRef.current = []
      mr.ondataavailable = e => chunksRef.current.push(e.data)
      mr.start()
      mediaRef.current = mr
      setRecording(true)
    } catch {
      alert('Microphone access denied. Use text input instead.')
      setMode('text')
    }
  }

  async function stopAndProcess() {
    setRecording(false)
    return new Promise<void>(resolve => {
      if (!mediaRef.current) return resolve()
      mediaRef.current.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        await launch(blob)
        resolve()
      }
      mediaRef.current.stop()
    })
  }

  async function launch(audioBlob?: Blob) {
    const text = textInput.trim()
    if (!audioBlob && !text) return
    if (loadingRef.current) return   // guard against accidental double-clicks
    loadingRef.current = true

    setLoading(true)
    setStatus('Creating your studio session...')

    try {
      const { session_id } = await api.createSession()
      let transcript = text

      if (audioBlob) {
        setStatus('Transcribing your idea with Whisper...')
        const fd = new FormData()
        fd.append('audio', audioBlob, 'idea.webm')
        const res = await api.submitAudio(session_id, fd)
        transcript = res.transcript
      }

      setStatus('Launching Nolan Studio...')
      router.push(`/session/${session_id}?transcript=${encodeURIComponent(transcript)}`)
    } catch (err) {
      console.error(err)
      setStatus('Something went wrong. Please try again.')
      setLoading(false)
      loadingRef.current = false
    }
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: -30 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-12"
      >
        <div className="flex items-center justify-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-nolan-accent flex items-center justify-center">
            <Radio className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-5xl font-bold tracking-tight text-white">NOLAN</h1>
        </div>
        <p className="text-nolan-muted text-base mt-2">
          Tell me a dream, a memory, or a rough idea.
        </p>
        <p className="text-nolan-accent text-sm font-medium mt-1">
          I'll turn it into a cinematic audio pilot.
        </p>
      </motion.div>

      {/* Main input card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="glass rounded-2xl p-6 w-full max-w-xl"
      >
        {/* Mode tabs */}
        <div className="flex gap-2 mb-5 bg-nolan-surface rounded-xl p-1">
          <button
            onClick={() => setMode('text')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'text' ? 'bg-nolan-accent text-white' : 'text-nolan-muted hover:text-white'
            }`}
          >
            <Type className="w-4 h-4" /> Type your idea
          </button>
          <button
            onClick={() => setMode('voice')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'voice' ? 'bg-nolan-accent text-white' : 'text-nolan-muted hover:text-white'
            }`}
          >
            <Mic className="w-4 h-4" /> Speak your idea
          </button>
        </div>

        <AnimatePresence mode="wait">
          {mode === 'text' ? (
            <motion.div key="text" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <textarea
                value={textInput}
                onChange={e => setTextInput(e.target.value)}
                placeholder="I dreamed that everyone forgot my name except a dead person who kept calling me..."
                rows={4}
                disabled={loading}
                className="w-full bg-nolan-surface border border-nolan-border rounded-xl p-4 text-sm text-nolan-text placeholder:text-nolan-muted/50 resize-none focus:outline-none focus:border-nolan-accent transition-colors"
              />

              {/* Example prompts */}
              <div className="mt-3 mb-4">
                <p className="text-nolan-muted text-xs mb-2">Try an example:</p>
                <div className="flex flex-col gap-1.5">
                  {EXAMPLES.map((ex, i) => (
                    <button
                      key={i}
                      onClick={() => setTextInput(ex)}
                      className="text-left text-xs text-nolan-muted hover:text-nolan-accent border border-transparent hover:border-nolan-accent/30 rounded-lg px-3 py-1.5 transition-all"
                    >
                      "{ex.slice(0, 65)}..."
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={() => launch()}
                disabled={loading || !textInput.trim()}
                className="w-full py-3 bg-nolan-accent text-white rounded-xl font-bold text-sm hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2"
              >
                {loading
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> {status}</>
                  : <><Sparkles className="w-4 h-4" /> Compile Imagination <ArrowRight className="w-4 h-4" /></>
                }
              </button>
            </motion.div>
          ) : (
            <motion.div key="voice" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-5 py-4"
            >
              <p className="text-nolan-muted text-sm text-center">
                Speak freely — a dream, a memory, a half-formed idea.<br/>
                <span className="text-nolan-accent text-xs">It does not need to be complete.</span>
              </p>

              <motion.button
                whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
                onClick={recording ? stopAndProcess : startRecording}
                disabled={loading}
                className={`w-24 h-24 rounded-full flex flex-col items-center justify-center gap-1 font-medium text-xs transition-all ${
                  recording
                    ? 'bg-nolan-red text-white animate-pulse_slow shadow-[0_0_40px_rgba(255,77,109,0.4)]'
                    : 'bg-nolan-accent text-white hover:shadow-[0_0_30px_rgba(108,71,255,0.5)]'
                }`}
              >
                {loading
                  ? <Loader2 className="w-8 h-8 animate-spin" />
                  : recording ? <><MicOff className="w-8 h-8" /><span>STOP</span></>
                  : <><Mic className="w-8 h-8" /><span>SPEAK</span></>
                }
              </motion.button>

              {recording && (
                <p className="text-nolan-red text-xs animate-pulse">Recording... tap to stop</p>
              )}
              {loading && status && (
                <p className="text-nolan-muted text-xs animate-pulse">{status}</p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* How it works */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
        className="mt-10 flex items-center gap-3 text-xs text-nolan-muted"
      >
        {['Your idea', 'Creative DNA', '3 Visions', 'Story Check', 'Audio Pilot'].map((step, i, arr) => (
          <span key={step} className="flex items-center gap-3">
            <span className="text-center">
              <span className="block w-6 h-6 rounded-full bg-nolan-surface border border-nolan-border text-nolan-muted text-[10px] flex items-center justify-center mx-auto mb-1">{i + 1}</span>
              {step}
            </span>
            {i < arr.length - 1 && <ArrowRight className="w-3 h-3 opacity-30 flex-shrink-0" />}
          </span>
        ))}
      </motion.div>

      <p className="mt-8 text-nolan-muted/40 text-xs tracking-widest">
        POCKET FM × OPENAI — ZERO TO ONE
      </p>
    </main>
  )
}
