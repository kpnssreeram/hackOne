'use client'
import { useEffect, useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Mic, MicOff, Type, Loader2, Sparkles, ArrowRight, Clapperboard, PenLine } from 'lucide-react'
import { api } from '@/lib/api'

const EXAMPLES = [
  "I dreamed the entire world forgot me, but my dead brother kept calling my phone.",
  "A food delivery driver gets an order from his missing sister's old address.",
  "Two strangers discover they've been having the same dream for a year.",
  "A woman finds her own obituary — dated three days from now.",
]

const LANGUAGE_OPTIONS = [
  { value: 'auto', label: 'Use the language I speak/write' },
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'kn', label: 'Kannada' },
  { value: 'ml', label: 'Malayalam' },
]

export default function Home() {
  const router = useRouter()
  const [mode, setMode] = useState<'voice' | 'text'>('text')
  const [recording, setRecording] = useState(false)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [textInput, setTextInput] = useState('')
  const [outputLanguage, setOutputLanguage] = useState('auto')
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const releaseRecorder = (recorder: MediaRecorder | null) => {
    recorder?.stream.getTracks().forEach(track => track.stop())
    if (mediaRef.current === recorder) mediaRef.current = null
  }

  const cancelRecording = () => {
    const recorder = mediaRef.current
    if (!recorder) return
    recorder.onstop = null
    if (recorder.state !== 'inactive') recorder.stop()
    releaseRecorder(recorder)
    setRecording(false)
  }

  useEffect(() => () => {
    const recorder = mediaRef.current
    if (!recorder) return
    recorder.onstop = null
    if (recorder.state !== 'inactive') recorder.stop()
    recorder.stream.getTracks().forEach(track => track.stop())
    mediaRef.current = null
  }, [])

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
      const recorder = mediaRef.current
      if (!recorder) return resolve()
      recorder.onstop = async () => {
        try {
          const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
          await launch(blob)
        } finally {
          releaseRecorder(recorder)
          resolve()
        }
      }
      recorder.stop()
    })
  }

  async function launch(audioBlob?: Blob) {
    const text = textInput.trim()
    if (!audioBlob && !text) return

    setLoading(true)
    setStatus('Creating your studio session...')

    try {
      const { session_id } = await api.createSession()
      let transcript = text

      if (audioBlob) {
        setStatus('Transcribing your idea with Whisper...')
        const fd = new FormData()
        fd.append('audio', audioBlob, 'idea.webm')
        fd.append('language', outputLanguage)
        const res = await api.submitAudio(session_id, fd)
        transcript = res.transcript
      }

      setStatus('Launching Nolan Studio...')
      router.push(`/session/${session_id}?transcript=${encodeURIComponent(transcript)}&language=${encodeURIComponent(outputLanguage)}`)
    } catch (err) {
      console.error(err)
      setStatus('Something went wrong. Please try again.')
      setLoading(false)
    }
  }

  return (
    <main className="lovable-home min-h-screen">
      <header className="lovable-home-header">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5"><div className="flex items-center gap-3"><span className="nolan-mark" aria-hidden="true"><span /></span><span className="nolan-wordmark">NOLAN</span></div><p className="hidden text-sm text-[#a59a8c] sm:block">One breath in. One binge-worthy episode out.</p></div>
      </header>
      <section className="lovable-hero mx-auto grid max-w-7xl items-center gap-12 px-6 py-16 lg:grid-cols-[1.15fr_.85fr] lg:py-28">
        <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }}>
          <div className="lovable-session-pill"><span className="nolan-mark !h-5 !w-5" aria-hidden="true"><span /></span> NOW IN SESSION <i /> Vol. I · Reel 01</div>
          <h1 className="lovable-title mt-9">Every great<br/>story begins with an<br/><em>idea.</em></h1>
          <p className="lovable-copy mt-9">Let AI become your creative partner. Whisper a premise — Nolan&apos;s writers&apos; room turns half-dreams and midnight memories into serialised cinematic drama.</p>
          <p className="mt-10 text-[11px] font-semibold uppercase tracking-[.22em] text-[#b78653]">◉ Hear a sample chapter&nbsp; → <span className="ml-4 normal-case italic tracking-normal text-[#b3a79a]">no account · no waiting · just listen</span></p>
        </motion.div>
        <motion.div initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .12 }} className="recording-booth">
          <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[.22em] text-[#a79b8d]"><span>Recording booth · Take 01</span><span className="text-[#b78653]">● Ready</span></div>
          <div className="mt-10 flex rounded-full bg-[#f3f0e9] p-1 text-sm">
          <button
            onClick={() => { if (recording) cancelRecording(); setMode('text') }}
            className={`flex-1 py-2.5 rounded-full font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'text' ? 'bg-white text-stone-800 shadow-sm' : 'text-[#9e9388]'
            }`}
          >
            <Type className="w-4 h-4" /> Text
          </button>
          <button
            onClick={() => { if (recording) cancelRecording(); setMode('voice') }}
            className={`flex-1 py-2.5 rounded-full font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'voice' ? 'bg-white text-stone-800 shadow-sm' : 'text-[#9e9388]'
            }`}
          >
            <Mic className="w-4 h-4" /> Voice
          </button>
        </div>
        <AnimatePresence mode="wait">
          {mode === 'text' ? (
            <motion.div key="text" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-8">
              <textarea
                value={textInput}
                onChange={e => setTextInput(e.target.value)}
                placeholder="Tell us the story only you can tell…"
                rows={6}
                disabled={loading}
                className="booth-textarea w-full resize-none p-4 text-sm text-stone-700 placeholder:text-[#b8aea2] focus:outline-none"
              />
              <button
                onClick={() => launch()}
                disabled={loading || !textInput.trim()}
                className="booth-primary mt-4 w-full py-3 text-sm font-bold text-white disabled:opacity-40 flex items-center justify-center gap-2"
              >
                {loading
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> {status}</>
                  : <><Sparkles className="w-4 h-4" /> Tell Nolan my story <ArrowRight className="w-4 h-4" /></>
                }
              </button>
            </motion.div>
          ) : (
            <motion.div key="voice" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-5 py-10"
            >
              <motion.button
                whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
                onClick={recording ? stopAndProcess : startRecording}
                disabled={loading}
                className={`w-28 h-28 rounded-full flex flex-col items-center justify-center gap-1 font-medium text-xs transition-all ${
                  recording
                    ? 'bg-[#c74429] text-white animate-pulse_slow shadow-[0_0_40px_rgba(199,68,41,0.3)]'
                    : 'bg-[#292529] text-white hover:shadow-[0_0_30px_rgba(41,37,41,0.22)]'
                }`}
              >
                {loading
                  ? <Loader2 className="w-8 h-8 animate-spin" />
                  : recording ? <><MicOff className="w-8 h-8" /><span>STOP</span></>
                  : <><Mic className="w-8 h-8" /><span>SPEAK</span></>
                }
              </motion.button>

              {recording && (
                <p className="text-[#c74429] text-xs animate-pulse">Recording... tap to stop</p>
              )}
              {loading && status && (
                <p className="text-[#9e9388] text-xs animate-pulse">{status}</p>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        <label className="block mt-5 text-[10px] font-bold uppercase tracking-[.16em] text-[#a79b8d]">
          Story language
          <select value={outputLanguage} onChange={e => setOutputLanguage(e.target.value)} disabled={loading}
            className="booth-select mt-2 w-full px-3 py-2 text-sm text-stone-700 focus:outline-none">
            {LANGUAGE_OPTIONS.map(language => <option key={language.value} value={language.value}>{language.label}</option>)}
          </select>
        </label>
      </motion.div>
      </section>
      <footer className="mx-auto max-w-7xl px-6 pb-8 text-[10px] uppercase tracking-[.2em] text-[#a99f94]">The craft <span className="float-right normal-case italic tracking-normal">a small library of listenable fiction</span></footer>
    </main>
  )
}
