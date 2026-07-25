'use client'
import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Mic, MicOff, Type, Loader2, Sparkles, Radio } from 'lucide-react'
import { api } from '@/lib/api'

const DEMO_PROMPT = "I dreamed the entire world forgot me, but my dead brother kept calling my phone. Make it mysterious and emotional."

export default function Home() {
  const router = useRouter()
  const [mode, setMode] = useState<'voice'|'text'>('voice')
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [status, setStatus] = useState('')
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
    chunksRef.current = []
    mr.ondataavailable = e => chunksRef.current.push(e.data)
    mr.start()
    mediaRef.current = mr
    setRecording(true)
  }

  async function stopAndProcess() {
    setRecording(false)
    setProcessing(true)
    setStatus('Transcribing your idea...')

    return new Promise<void>(resolve => {
      if (!mediaRef.current) return resolve()
      mediaRef.current.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        await processIdea(blob)
        resolve()
      }
      mediaRef.current.stop()
    })
  }

  async function processText() {
    setProcessing(true)
    setStatus('Sending your idea to Nolan...')
    await processIdea(null, textInput || DEMO_PROMPT)
  }

  async function processIdea(audioBlob: Blob | null, text?: string) {
    try {
      // 1. Create session
      setStatus('Creating session...')
      const { session_id } = await api.createSession()

      // 2. Transcribe or use text
      let transcript = text || ''
      if (audioBlob) {
        setStatus('Transcribing with Whisper...')
        const fd = new FormData()
        fd.append('audio', audioBlob, 'idea.webm')
        const res = await api.submitAudio(session_id, fd)
        transcript = res.transcript
      }

      // 3. Extract DNA (starts streaming on session page)
      router.push(`/session/${session_id}?transcript=${encodeURIComponent(transcript)}`)
    } catch (err) {
      setStatus('Something went wrong. Try again.')
      setProcessing(false)
    }
  }

  async function useDemoPrompt() {
    setTextInput(DEMO_PROMPT)
    setMode('text')
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-16"
      >
        <div className="flex items-center justify-center gap-3 mb-4">
          <Radio className="w-8 h-8 text-nolan-accent" />
          <h1 className="text-5xl font-bold tracking-tight">
            <span className="text-white">NOLAN</span>
          </h1>
        </div>
        <p className="text-nolan-muted text-lg tracking-widest uppercase">
          One breath in. One binge-worthy episode out.
        </p>
      </motion.div>

      {/* Main card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2 }}
        className="glass rounded-2xl p-8 w-full max-w-2xl"
      >
        {/* Mode toggle */}
        <div className="flex gap-2 mb-8 p-1 bg-nolan-surface rounded-xl">
          <button
            onClick={() => setMode('voice')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm transition-all ${
              mode === 'voice' ? 'bg-nolan-accent text-white' : 'text-nolan-muted hover:text-white'
            }`}
          >
            <Mic className="w-4 h-4" /> Voice Input
          </button>
          <button
            onClick={() => setMode('text')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm transition-all ${
              mode === 'text' ? 'bg-nolan-accent text-white' : 'text-nolan-muted hover:text-white'
            }`}
          >
            <Type className="w-4 h-4" /> Text Input
          </button>
        </div>

        <AnimatePresence mode="wait">
          {mode === 'voice' ? (
            <motion.div
              key="voice"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-6"
            >
              <p className="text-nolan-muted text-center text-sm">
                Tell Nolan a dream, memory, character, or idea.<br />
                <span className="text-nolan-accent">It does not need to be complete.</span>
              </p>

              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={recording ? stopAndProcess : startRecording}
                disabled={processing}
                className={`relative w-28 h-28 rounded-full flex items-center justify-center transition-all ${
                  recording
                    ? 'bg-nolan-red animate-pulse_slow shadow-[0_0_40px_rgba(255,77,109,0.5)]'
                    : 'bg-nolan-accent hover:shadow-[0_0_30px_rgba(108,71,255,0.6)]'
                }`}
              >
                {processing ? (
                  <Loader2 className="w-10 h-10 text-white animate-spin" />
                ) : recording ? (
                  <MicOff className="w-10 h-10 text-white" />
                ) : (
                  <Mic className="w-10 h-10 text-white" />
                )}
                {recording && (
                  <span className="absolute -bottom-8 text-nolan-red text-xs tracking-widest animate-pulse">
                    RECORDING... TAP TO STOP
                  </span>
                )}
              </motion.button>

              {status && (
                <p className="text-nolan-muted text-sm animate-pulse">{status}</p>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="text"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col gap-4"
            >
              <textarea
                value={textInput}
                onChange={e => setTextInput(e.target.value)}
                placeholder="I dreamed that everyone forgot my name except a dead person..."
                rows={4}
                className="w-full bg-nolan-surface border border-nolan-border rounded-xl p-4 text-nolan-text text-sm resize-none focus:outline-none focus:border-nolan-accent transition-colors"
              />
              <div className="flex gap-3">
                <button
                  onClick={useDemoPrompt}
                  className="flex items-center gap-2 px-4 py-2 text-xs text-nolan-muted border border-nolan-border rounded-lg hover:border-nolan-accent hover:text-white transition-all"
                >
                  <Sparkles className="w-3 h-3" /> Use Demo
                </button>
                <button
                  onClick={processText}
                  disabled={processing || !textInput.trim()}
                  className="flex-1 flex items-center justify-center gap-2 py-2 bg-nolan-accent text-white rounded-lg text-sm hover:opacity-90 disabled:opacity-40 transition-all"
                >
                  {processing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                  {processing ? status : 'Compile Imagination'}
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Footer */}
      <p className="mt-8 text-nolan-muted text-xs tracking-widest">
        POCKET FM × OPENAI — ZERO TO ONE HACKATHON
      </p>
    </main>
  )
}
