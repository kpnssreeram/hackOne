'use client'
import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { useSSE } from '@/lib/sse'
import { api } from '@/lib/api'
import {
  Mic, Lock, Unlock, Play, Pause, CheckCircle, XCircle,
  Sparkles, Radio, Loader2, Volume2, GitBranch, Shield,
  Wand2, ChevronRight, ChevronDown, RefreshCw, Film, Upload, X, CircleDot,
} from 'lucide-react'

// ─── Step definition ──────────────────────────────────────────────────────────
const STEPS = [
  { id: 'dna',         label: 'Story',      icon: Sparkles  },
  { id: 'visions',     label: 'Direction',  icon: GitBranch },
  { id: 'production',  label: 'Script',     icon: Shield    },
  { id: 'audio',       label: 'Episode',    icon: Volume2   },
]

type Step = 'dna' | 'visions' | 'production' | 'audio'
type SeriesFormat = 'audio' | 'video'

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
type StudioUpdate = { role: string; text: string; color: 'purple' | 'blue' | 'gold' }
type VoiceOption = { voice_id: string; name: string; gender: string; category: string }
type AudioPollResult = 'audio_ready' | 'script_ready' | 'error' | 'timeout' | 'cancelled'
type EpisodeStatus = 'OUTLINED' | 'DRAFTING' | 'DRAFT_READY' | 'RENDERING' | 'READY' | 'APPROVED' | 'REVISING' | 'STALE'
type EpisodeOutline = {
  number: number; title: string; what_happens: string; emotional_turn: string; ending_promise: string
}
type EpisodeFeedback = { keep: string; change_this_episode: string; next_direction: string }
type ScriptLine = { type: 'ambience' | 'sfx' | 'silence' | 'dialogue' | 'music'; character?: string | null; text?: string | null; emotion?: string | null; voice_note?: string | null; duration_seconds?: number | null; description?: string | null }
type ProductionScript = { title: string; lines: ScriptLine[]; estimated_duration_seconds: number }
type StoryEpisode = {
  number: number; outline: EpisodeOutline; status: EpisodeStatus
  production_script?: ProductionScript | null; poster_prompt?: string | null
  constitution_report?: { checks: Check[]; overall_score: number } | null
  feedback?: EpisodeFeedback | null; continuity_summary?: string | null
  audio_url?: string | null; cover_image_url?: string | null; actual_duration_seconds?: number | null
  visual_episode_plan?: any | null
  visual_episode?: VisualEpisodeResult | null
}
type SeriesPlan = {
  title: string; logline: string; tone: string; ending_promise: string; episode_outlines: EpisodeOutline[]
}
type StoryAsset = { id: string; kind: 'photo' | 'video' | 'place_reference'; filename: string; url: string; consented: boolean }
type VisualEpisodeResult = { status: 'planned' | 'rendering' | 'ready' | 'failed'; url?: string | null; message?: string | null; provider_job_id?: string | null; progress?: number | null }

const CONSTITUTION_RULES = [
  { rule_number: 1, rule: 'Hook within 15 seconds' },
  { rule_number: 2, rule: 'Audio clarity' },
  { rule_number: 3, rule: 'Escalation' },
  { rule_number: 4, rule: 'Motivation' },
  { rule_number: 5, rule: 'Sound purpose' },
  { rule_number: 6, rule: 'Narration economy' },
  { rule_number: 7, rule: 'Cliffhanger / ending payoff' },
  { rule_number: 8, rule: 'DNA lock' },
]

const AGENT_COLOR: Record<string, string> = {
  muse: 'text-purple-400', writer: 'text-blue-400',
  supervisor: 'text-yellow-400', audio_director: 'text-green-400',
  director: 'text-purple-400',
}

const wait = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))

const CAMEO_MAX_SECONDS = 10
const MIN_AUDIO_SECONDS = 60
const CAMEO_SAMPLE_SCRIPTS: Record<string, string> = {
  en: 'I confirm this is my voice. I am speaking clearly and naturally for Nolan. The rain is coming, and something important is about to change.',
  hi: 'मैं पुष्टि करता या करती हूँ कि यह मेरी आवाज़ है। मैं नोलन के लिए साफ़ और स्वाभाविक रूप से बोल रहा या रही हूँ। बारिश आ रही है, और कुछ महत्वपूर्ण बदलने वाला है।',
  te: 'ఇది నా స్వరం అని నేను ధృవీకరిస్తున్నాను. నేను నోలన్ కోసం స్పష్టంగా, సహజంగా మాట్లాడుతున్నాను. వర్షం వస్తోంది, ఒక ముఖ్యమైన విషయం మారబోతోంది.',
  ta: 'இது என் குரல் என்பதை நான் உறுதிப்படுத்துகிறேன். நோலனுக்காக தெளிவாகவும் இயல்பாகவும் பேசுகிறேன். மழை வருகிறது; முக்கியமான ஒன்று மாறப் போகிறது.',
}

const formatRecordingTime = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`

const formatPlaybackTime = (seconds: number) => {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  return `${String(Math.floor(safeSeconds / 60)).padStart(1, '0')}:${String(safeSeconds % 60).padStart(2, '0')}`
}

export default function SessionPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const sessionId = params.id as string
  const transcript = searchParams.get('transcript') || ''
  const requestedLanguage = searchParams.get('language') || 'auto'

  const [step, setStep] = useState<Step>('dna')
  const [busy, setBusy] = useState(false)
  const [sseUrl, setSseUrl] = useState<string | null>(null)
  const [transcriptDraft, setTranscriptDraft] = useState(transcript)
  const [storyApproved, setStoryApproved] = useState(false)
  const [protagonistHint, setProtagonistHint] = useState('')
  const [characterHints, setCharacterHints] = useState('')
  const [storyError, setStoryError] = useState('')
  const [studioUpdate, setStudioUpdate] = useState<StudioUpdate>({ role: 'Muse', text: 'Ready to discover the heart of your story.', color: 'purple' })
  const [jarvisOpen, setJarvisOpen] = useState(false)

  const [dna, setDna] = useState<DNA | null>(null)
  const [lockedFields, setLockedFields] = useState<Set<string>>(new Set())
  const [voiceCast, setVoiceCast] = useState<Record<string, string>>({})
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([])
  const [seriesFormat, setSeriesFormat] = useState<SeriesFormat>('audio')
  const [videoFileOne, setVideoFileOne] = useState<File | null>(null)
  const [videoFileTwo, setVideoFileTwo] = useState<File | null>(null)
  const [videoConsent, setVideoConsent] = useState(false)
  const [videoUploadError, setVideoUploadError] = useState('')
  const [videoSourcesSaved, setVideoSourcesSaved] = useState(false)

  const [visions, setVisions] = useState<Vision[]>([])
  const [selectedVision, setSelectedVision] = useState<string>('')
  const [seriesPlan, setSeriesPlan] = useState<SeriesPlan | null>(null)
  const [episodes, setEpisodes] = useState<StoryEpisode[]>([])
  const [activeEpisodeNumber, setActiveEpisodeNumber] = useState(1)
  const [episodeFeedback, setEpisodeFeedback] = useState<Record<number, EpisodeFeedback>>({})

  const [termLines, setTermLines] = useState<TermLine[]>([])
  const [tokenBuf, setTokenBuf] = useState('')

  const [checks, setChecks] = useState<Check[]>([])
  const [score, setScore] = useState<number | null>(null)

  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioEpisodeNumber, setAudioEpisodeNumber] = useState<number | null>(null)
  const [audioError, setAudioError] = useState('')
  const [scriptReady, setScriptReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [audioCurrentTime, setAudioCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)

  const [revise, setRevise] = useState('')
  const [lockDiff, setLockDiff] = useState<any>(null)
  const [visualError, setVisualError] = useState('')
  const [visualPlan, setVisualPlan] = useState<any>(null)
  const [visualResult, setVisualResult] = useState<VisualEpisodeResult | null>(null)
  const [coverImageUrl, setCoverImageUrl] = useState<string | null>(null)
  const [coverError, setCoverError] = useState('')
  const [coverGenerating, setCoverGenerating] = useState(false)
  const [coverIsFallback, setCoverIsFallback] = useState(false)
  const [posterReferenceFile, setPosterReferenceFile] = useState<File | null>(null)
  const [posterReferenceConsent, setPosterReferenceConsent] = useState(false)
  const [posterReferenceSaved, setPosterReferenceSaved] = useState(false)
  const [posterReferenceError, setPosterReferenceError] = useState('')
  const [posterPrompt, setPosterPrompt] = useState('')
  const [scriptEditMode, setScriptEditMode] = useState(false)
  const [scriptDraft, setScriptDraft] = useState<ProductionScript | null>(null)
  const [scriptSaveError, setScriptSaveError] = useState('')
  const [storyAssets, setStoryAssets] = useState<StoryAsset[]>([])
  const [cameoFile, setCameoFile] = useState<File | null>(null)
  const [cameoStatus, setCameoStatus] = useState('')
  const [cameoConsent, setCameoConsent] = useState(false)
  const [cameoRole, setCameoRole] = useState<'narrator' | 'character'>('narrator')
  const [cameoCharacterName, setCameoCharacterName] = useState<string | null>(null)
  const [cameoRecording, setCameoRecording] = useState(false)
  const [cameoSeconds, setCameoSeconds] = useState(0)
  const [cameoRecorderError, setCameoRecorderError] = useState('')

  const audioRef = useRef<HTMLAudioElement>(null)
  const termRef  = useRef<HTMLDivElement>(null)
  const workflowSequenceRef = useRef(0)
  const activeWorkflowRef = useRef<number | null>(null)
  const cameoRecorderRef = useRef<MediaRecorder | null>(null)
  const cameoStreamRef = useRef<MediaStream | null>(null)
  const cameoTimerRef = useRef<number | null>(null)

  // Auto-scroll terminal
  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
  }, [termLines, tokenBuf])

  useEffect(() => {
    const episode = episodes.find(item => item.number === activeEpisodeNumber)
    if (episode?.production_script) {
      setScriptDraft(JSON.parse(JSON.stringify(episode.production_script)))
      setScriptEditMode(false)
      setScriptSaveError('')
      setPosterPrompt(episode.poster_prompt || '')
    }
  }, [activeEpisodeNumber, episodes])

  const pushLine = useCallback((agent: string, text: string, type = 'status') => {
    setTermLines(prev => [...prev, { agent, text, type }])
  }, [])

  const beginWorkflow = useCallback(() => {
    const runId = ++workflowSequenceRef.current
    activeWorkflowRef.current = runId
    setBusy(true)
    return runId
  }, [])

  const isWorkflowActive = useCallback((runId: number) => activeWorkflowRef.current === runId, [])

  const finishWorkflow = useCallback((runId?: number) => {
    const activeRunId = activeWorkflowRef.current
    if (activeRunId === null || (runId !== undefined && activeRunId !== runId)) return false
    activeWorkflowRef.current = null
    setBusy(false)
    setSseUrl(null)
    return true
  }, [])

  const markScriptReady = useCallback((message?: string) => {
    setScriptReady(true)
    setStep('production')
    if (message) setAudioError(message)
  }, [])

  function clearCameoTimer() {
    if (cameoTimerRef.current !== null) {
      window.clearInterval(cameoTimerRef.current)
      cameoTimerRef.current = null
    }
  }

  function releaseCameoMicrophone() {
    cameoStreamRef.current?.getTracks().forEach(track => track.stop())
    cameoStreamRef.current = null
  }

  // Always release an active microphone if the creator leaves this page.
  useEffect(() => () => {
    clearCameoTimer()
    const recorder = cameoRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.stop()
    }
    releaseCameoMicrophone()
  }, [])

  useEffect(() => {
    setAudioCurrentTime(0)
    setAudioDuration(0)
  }, [audioUrl])

  // Keep one small source of truth for both live events and a returning
  // creator. The series is saved server-side, so a refresh never loses an
  // approved episode or makes a later episode look ready too early.
  const hydrateSession = useCallback((saved: any) => {
    if (!saved?.creative_dna) return
    setDna(saved.creative_dna)
    setLockedFields(new Set(saved.creative_dna.locked_fields || []))
    setSeriesFormat(saved.preferences?.output_mode === 'video' ? 'video' : 'audio')
    setVoiceCast(saved.preferences?.voice_cast || {})
    setVisions(saved.visions || [])
    setSelectedVision(saved.selected_vision?.primary_vision_id || '')
    setSeriesPlan(saved.series_plan || null)
    setEpisodes(saved.episodes || [])
    setStoryAssets(saved.visual_assets || [])
    setPosterReferenceSaved((saved.visual_assets || []).some((asset: StoryAsset) => asset.kind === 'photo' && asset.filename.startsWith('poster-reference-')))
    setVideoSourcesSaved((saved.visual_assets || []).filter((asset: StoryAsset) => asset.kind === 'video' && asset.filename.startsWith('series-video_')).length >= 2)

    const activeNumber = saved.active_episode_number || 1
    const activeEpisode = (saved.episodes || []).find((episode: StoryEpisode) => episode.number === activeNumber)
    setActiveEpisodeNumber(activeNumber)
    setChecks(activeEpisode?.constitution_report?.checks || saved.constitution_report?.checks || [])
    setScore(activeEpisode?.constitution_report?.overall_score ?? saved.constitution_report?.overall_score ?? null)
    setScriptReady(Boolean(activeEpisode?.production_script || saved.production_script))
    const coverUrl = activeEpisode?.cover_image_url || saved.cover_image_url
    setCoverImageUrl(coverUrl ? api.absoluteUrl(coverUrl) : null)
    setCoverIsFallback(Boolean(coverUrl?.endsWith('.svg')))
    setVisualPlan(activeEpisode?.visual_episode_plan || saved.visual_episode_plan || null)
    setVisualResult(activeEpisode?.visual_episode || saved.visual_episode || null)

    // A series can legitimately be on Episode 2 while only Episode 1 has
    // finished rendering. Prefer the active episode when it has audio, then
    // fall back to the newest playable episode. Never let an empty active
    // draft erase an older playable episode from the UI.
    const savedEpisodes = (saved.episodes || []) as StoryEpisode[]
    const playableEpisode = activeEpisode?.audio_url
      ? activeEpisode
      : [...savedEpisodes].sort((a, b) => b.number - a.number).find(episode => episode.audio_url)
    const audio = playableEpisode?.audio_url || (!saved.series_plan ? saved.audio_url : null)
    if (audio) {
      setAudioUrl(api.absoluteUrl(audio))
      setAudioEpisodeNumber(playableEpisode?.number || null)
      setStep('audio')
    } else if (activeEpisode?.production_script || saved.production_script) {
      if (!saved.series_plan) {
        setAudioUrl(null)
        setAudioEpisodeNumber(null)
      }
      setStep('production')
      if (saved.status === 'CONSTITUTION_DONE' || saved.status === 'ERROR' || saved.status === 'SCRIPT_READY') {
        setAudioError('The story is ready, but the audio take needs another render.')
      }
    } else if ((saved.visions || []).length) {
      setStep('visions')
    }
  }, [])

  const refreshSession = useCallback(async () => {
    const saved = await api.getSession(sessionId)
    hydrateSession(saved)
    return saved
  }, [sessionId, hydrateSession])

  // ─── SSE handler ─────────────────────────────────────────────────────────────
  const handleSSE = useCallback((e: any) => {
    if (e.type === 'token') {
      // Muse streams its machine-readable brief. The creator sees the finished
      // story card, not a wall of JSON.
      if (e.agent === 'muse') return
      setTokenBuf(prev => prev + (typeof e.data === 'string' ? e.data : ''))
      return
    }

    // Flush token buffer
    setTokenBuf(prev => {
      if (prev.trim()) pushLine(e.agent, prev, 'token')
      return ''
    })

    if (e.type === 'status') {
      pushLine(e.agent, String(e.data), 'status')
      const room = e.agent === 'writer' ? { role: 'Writer', color: 'blue' as const }
        : e.agent === 'supervisor' ? { role: 'Story guide', color: 'gold' as const }
        : e.agent === 'audio_director' ? { role: 'Sound designer', color: 'gold' as const }
        : e.agent === 'director' ? { role: 'Story director', color: 'purple' as const }
        : { role: 'Muse', color: 'purple' as const }
      setStudioUpdate({ ...room, text: String(e.data) })
    }
    if (e.type === 'fallback') pushLine(e.agent, `⚡ ${e.data}`, 'fallback')
    if (e.type === 'error') {
      pushLine(e.agent, `✗ ${e.data}`, 'error')
      if (e.agent === 'audio_director') {
        markScriptReady(String(e.data))
      }
      finishWorkflow()
      setBusy(false)
      setSseUrl(null)
      return
    }

    if (e.type === 'violation') {
      const c = e.data as Check
      setChecks(prev => [...prev.filter(x => x.rule_number !== c.rule_number), c])
    }

    if (e.type === 'artifact') {
      const d = e.data
      // DNA arrived
      if (d?.core_emotion) { setDna(d); setStep('visions'); setBusy(false) }
      // Vision artifacts arrive one at a time over SSE. Keeping them here
      // avoids a fragile one-shot poll and makes the three-card audition real.
      if (d?.id && d?.opening_preview) {
        setVisions(prev => prev.some(v => v.id === d.id) ? prev.map(v => v.id === d.id ? d : v) : [...prev, d])
        setBusy(false)
      }
      if (d?.rule_number && d?.rule) {
        setChecks(prev => [...prev.filter(x => x.rule_number !== d.rule_number), d])
      }
      // Constitution score
      if (d?.score !== undefined) setScore(d.score)
      // The series plan and an episode draft are compact, real artifacts from
      // the writer/director—not raw model JSON in the creator's feed.
      if (d?.series_plan) {
        setSeriesPlan(d.series_plan)
        setEpisodes(d.episodes || [])
        setActiveEpisodeNumber(1)
        setStep('production')
      }
      if (d?.episode?.number) {
        const episode = d.episode as StoryEpisode
        setEpisodes(previous => previous.some(item => item.number === episode.number)
          ? previous.map(item => item.number === episode.number ? episode : item)
          : [...previous, episode])
        setActiveEpisodeNumber(episode.number)
        setChecks(episode.constitution_report?.checks || [])
        setScore(episode.constitution_report?.overall_score ?? null)
        setScriptReady(Boolean(episode.production_script))
        setVisualPlan(episode.visual_episode_plan || null)
        setVisualResult(episode.visual_episode || null)
        if (episode.cover_image_url) {
          setCoverImageUrl(api.absoluteUrl(episode.cover_image_url))
          setCoverIsFallback(episode.cover_image_url.endsWith('.svg'))
        } else {
          setCoverImageUrl(null)
          setCoverIsFallback(false)
        }
        if (episode.audio_url) {
          setAudioUrl(api.absoluteUrl(episode.audio_url))
          setAudioEpisodeNumber(episode.number)
        }
        setStep(episode.audio_url ? 'audio' : 'production')
      }
      if (d?.visual_episode) setVisualResult(d.visual_episode as VisualEpisodeResult)
      // The script may arrive before the final mix. Keep a direct audio-only
      // retry available so a creator never has to remake their episode.
      if (d?.title && Array.isArray(d?.lines)) setScriptReady(true)
      // Creative lock diff
      if (d?.lock_diff) {
        setLockDiff(d.lock_diff)
        pushLine(e.agent, '✓ Your saved story details are protected', 'complete')
      }
    }

    if (e.type === 'complete') {
      const d = typeof e.data === 'object' ? e.data : {}
      if (d.url || d.audio_url) {
        setAudioUrl(api.absoluteUrl(d.url || d.audio_url))
        setAudioEpisodeNumber(typeof d.episode_number === 'number' ? d.episode_number : null)
        setStep('audio')
      } else if (typeof d.status === 'string' && (d.status.startsWith('EPISODE_') || d.status === 'SERIES_COMPLETE')) {
        void refreshSession().catch(() => undefined)
      } else if (d.status === 'SCRIPT_READY') {
        markScriptReady('The story is ready, but the audio take needs another render.')
      }
      finishWorkflow()
      setBusy(false)
      setSseUrl(null)
    }
  }, [sessionId, pushLine, markScriptReady, finishWorkflow, refreshSession])

  useSSE(sseUrl, handleSSE)

  // A refresh must restore the actual session artifacts, not replay stale UI
  // state from an earlier stream. This also lets a creator return to a pilot.
  useEffect(() => {
    if (!sessionId) return
    ;(async () => {
      try {
        await refreshSession()
      } catch {
        // A brand-new session has no saved artifacts yet.
      }
    })()
  }, [sessionId, refreshSession])

  // Load the actual ElevenLabs catalogue. These are the voices available to
  // this account, not a static list guessed by the frontend.
  useEffect(() => {
    ;(async () => {
      try {
        const result = await api.getVoices()
        setVoiceOptions(result.voices || [])
      } catch {
        // Auto presentation remains usable if a provider catalogue is briefly unavailable.
      }
    })()
  }, [])

  // ─── Boot: extract DNA on load ──────────────────────────────────────────────
  useEffect(() => {
    if (!storyApproved || !transcriptDraft.trim() || !sessionId) return
    ;(async () => {
      setBusy(true)
      setStoryError('')
      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({ role: 'Muse', text: 'Finding the people, genre, and emotional truth in your idea.', color: 'purple' })
      pushLine('director', 'Reading the dream and finding its cinematic world.')
      try {
        const optionalDetails = [
          protagonistHint.trim() && `The protagonist should be called ${protagonistHint.trim()}.`,
          characterHints.trim() && `Important characters to include: ${characterHints.trim()}.`,
        ].filter(Boolean).join(' ')
        await api.updatePreferences(sessionId, requestedLanguage)
        const result = await api.extractDNA(sessionId, `${transcriptDraft}\n\n${optionalDetails}`.trim(), requestedLanguage)
        if (result?.core_emotion) { setDna(result); setStep('visions') }
        else throw new Error('Nolan could not read the story.')
      } catch (error) {
        console.error(error)
        setStoryError('Nolan could not shape that yet. Please try once more — your words are still here.')
        pushLine('director', 'Let’s take one more pass at your story.')
        // The approval button remains visible after a failed request. Resetting
        // this flag lets the next click trigger the extraction effect again.
        setStoryApproved(false)
      } finally {
        setBusy(false)
        setSseUrl(null)
      }
    })()
  }, [storyApproved, sessionId, pushLine])

  const pollForAudioResult = useCallback(async (runId: number, attempts: number): Promise<AudioPollResult> => {
    let latestSession: any = null

    for (let attempt = 0; attempt < attempts; attempt++) {
      await wait(3000)
      if (!isWorkflowActive(runId)) return 'cancelled'

      try {
        latestSession = await api.getSession(sessionId)
      } catch (error) {
        // The SSE stream can still finish a workflow when a single fallback
        // poll fails, so keep trying instead of leaving the UI busy forever.
        console.error(error)
        continue
      }

      if (!isWorkflowActive(runId)) return 'cancelled'
      if (latestSession?.audio_url) {
        hydrateSession(latestSession)
        setAudioUrl(api.absoluteUrl(latestSession.audio_url))
        setAudioEpisodeNumber(latestSession.active_episode_number || null)
        setStep('audio')
        return 'audio_ready'
      }
      if ((latestSession?.status === 'SCRIPT_READY' || latestSession?.status === 'CONSTITUTION_DONE') && latestSession?.production_script) {
        markScriptReady('The story is ready, but the audio take needs another render.')
        return 'script_ready'
      }
      if (latestSession?.status === 'ERROR') {
        if (latestSession?.production_script) {
          markScriptReady('The story is safe, but the audio take needs another render.')
        }
        return 'error'
      }
    }

    if (!isWorkflowActive(runId)) return 'cancelled'
    if (latestSession?.production_script && !latestSession?.audio_url) {
      markScriptReady('The story is ready, but the audio take needs another render.')
      return 'script_ready'
    }
    return 'timeout'
  }, [isWorkflowActive, markScriptReady, sessionId, hydrateSession])

  // ─── Actions ──────────────────────────────────────────────────────────────────
  function chooseSeriesFormat(format: SeriesFormat) {
    setSeriesFormat(format)
    setVideoUploadError('')
    if (format === 'audio') {
      setVideoFileOne(null)
      setVideoFileTwo(null)
      setVideoConsent(false)
    }
    void api.updatePreferences(sessionId, requestedLanguage, voiceCast, format).catch(error => {
      console.error(error)
      setVideoUploadError('That format choice could not be saved yet. Please try again before rendering.')
    })
  }

  async function doSaveVideoSources() {
    if (seriesFormat !== 'video') return
    if (!videoFileOne || !videoFileTwo) {
      setVideoUploadError('Choose both source videos before continuing.')
      return
    }
    if (!videoConsent) {
      setVideoUploadError('Confirm that you own both videos or have permission to use them.')
      return
    }
    setBusy(true)
    setVideoUploadError('')
    try {
      await api.updatePreferences(sessionId, requestedLanguage, voiceCast, 'video')
      await api.uploadSeriesVideo(sessionId, 'video_1', videoFileOne, true)
      await api.uploadSeriesVideo(sessionId, 'video_2', videoFileTwo, true)
      await refreshSession()
      setVideoSourcesSaved(true)
      setVideoFileOne(null)
      setVideoFileTwo(null)
      setVideoConsent(false)
      pushLine('visual_director', 'Both source videos are saved. Nolan will cut them to the final audio master.', 'complete')
    } catch (error) {
      console.error(error)
      setVideoUploadError('Nolan could not save both videos. Check the file types and try again.')
    } finally {
      setBusy(false)
    }
  }

  async function doGenerateVisions() {
    if (!dna) return
    const runId = beginWorkflow()
    setStep('visions')
    setSseUrl(api.eventsUrl(sessionId))
    setStudioUpdate({ role: 'Writer', text: 'Auditioning three genuinely different ways to tell this story.', color: 'blue' })
    pushLine('writer', 'Finding three ways your story could feel…')
    try {
      await api.generateVisions(sessionId)
      // SSE is primary; polling remains a reliable fallback for slow browsers.
      for (let attempt = 0; attempt < 20; attempt++) {
        await wait(3000)
        if (!isWorkflowActive(runId)) return
        const s = await api.getSession(sessionId)
        if (s.visions?.length) {
          setVisions(s.visions)
          finishWorkflow(runId)
          return
        }
      }
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) {
        pushLine('writer', 'The three treatments could not be loaded. Try again.', 'error')
        finishWorkflow(runId)
      }
    } finally {
      if (isWorkflowActive(runId)) {
        pushLine('writer', 'The treatments are taking longer than expected. Please try again.', 'error')
      }
      finishWorkflow(runId)
    }
  }

  const chosenVision = () => ({
    primary_vision_id: selectedVision,
    opening_from: selectedVision,
    relationship_from: selectedVision,
    ending_from: selectedVision,
  })

  const episodeByNumber = (number: number) => episodes.find(episode => episode.number === number)

  const selectSeriesEpisode = (episode: StoryEpisode) => {
    setActiveEpisodeNumber(episode.number)
    setChecks(episode.constitution_report?.checks || [])
    setScore(episode.constitution_report?.overall_score ?? null)
    setScriptReady(Boolean(episode.production_script))
    setVisualPlan(episode.visual_episode_plan || null)
    setVisualResult(episode.visual_episode || null)
    if (episode.cover_image_url) {
      setCoverImageUrl(api.absoluteUrl(episode.cover_image_url))
      setCoverIsFallback(episode.cover_image_url.endsWith('.svg'))
    } else {
      setCoverImageUrl(null)
      setCoverIsFallback(false)
    }
    if (episode.audio_url) {
      setAudioUrl(api.absoluteUrl(episode.audio_url))
      setAudioEpisodeNumber(episode.number)
      setStep('audio')
    } else {
      setStep('production')
    }
  }

  const pollForSeries = useCallback(async (runId: number, done: (saved: any) => boolean, maxAttempts = 30) => {
    let latest: any = null
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await wait(1500)
      try {
        latest = await refreshSession()
      } catch (error) {
        console.error(error)
        continue
      }
      if (done(latest)) return true
      if (!isWorkflowActive(runId)) return false
    }
    return Boolean(latest && done(latest))
  }, [isWorkflowActive, refreshSession])

  async function doCreateSeries() {
    if (!selectedVision) return
    const runId = beginWorkflow()
    setStep('production')
    setAudioUrl(null)
    setAudioEpisodeNumber(null)
    setAudioError('')
    setChecks([])
    setSeriesPlan(null)
    setEpisodes([])
    try {
      await api.updatePreferences(sessionId, requestedLanguage, voiceCast, seriesFormat)
      if (!isWorkflowActive(runId)) return
      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({ role: 'Writer', text: 'Building the full three-episode arc before we spend on audio or visuals.', color: 'blue' })
      pushLine('writer', 'Planning the whole story: beginning, pressure, and ending.')
      await api.createSeries(sessionId, chosenVision())
      const planned = await pollForSeries(runId, saved => Boolean(saved.series_plan && saved.episodes?.length === 3))
      if (!planned && isWorkflowActive(runId)) {
        pushLine('writer', 'The story plan is taking longer than expected. Your idea is safe—please try again.', 'error')
      }
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) pushLine('writer', 'Nolan could not plan the series yet. Please try again.', 'error')
    } finally {
      finishWorkflow(runId)
    }
  }

  async function doDraftEpisode(episodeNumber: number) {
    const episode = episodeByNumber(episodeNumber)
    if (!episode) return
    const runId = beginWorkflow()
    setAudioError('')
    selectSeriesEpisode(episode)
    try {
      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({ role: 'Writer', text: `Writing Episode ${episodeNumber} from the choices you have already approved.`, color: 'blue' })
      pushLine('writer', `Writing Episode ${episodeNumber}: ${episode.outline.title}.`)
      await api.draftEpisode(sessionId, episodeNumber)
      const drafted = await pollForSeries(runId, saved =>
        saved.episodes?.some((item: StoryEpisode) => item.number === episodeNumber && item.status === 'DRAFT_READY'),
      )
      if (!drafted && isWorkflowActive(runId)) pushLine('writer', 'The episode draft is taking longer than expected. Please try again.', 'error')
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) pushLine('writer', 'Nolan could not draft this episode yet. Please try again.', 'error')
    } finally {
      finishWorkflow(runId)
    }
  }

  async function doConfirmEpisode(episodeNumber: number) {
    const episode = episodeByNumber(episodeNumber)
    if (!episode?.production_script) return
    if (seriesFormat === 'video' && !videoSourcesSaved && storyAssets.filter(asset => asset.kind === 'video' && asset.filename.startsWith('series-video_')).length < 2) {
      setVideoUploadError('Save both source videos before generating a video episode.')
      setStep('production')
      return
    }
    const runId = beginWorkflow()
    setAudioError('')
    selectSeriesEpisode(episode)
    try {
      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({ role: 'Sound designer', text: `Casting voices and mixing Episode ${episodeNumber} with its chosen language and emotion.`, color: 'gold' })
      pushLine('audio_director', `Creating the final audio for Episode ${episodeNumber}.`)
      await api.confirmEpisode(sessionId, episodeNumber)
      const ready = await pollForSeries(runId, saved =>
        saved.episodes?.some((item: StoryEpisode) => item.number === episodeNumber && item.status === 'READY' && item.audio_url),
      120)
      if (!ready && isWorkflowActive(runId)) pushLine('audio_director', 'Your audio is still finishing. Keep this page open; it will appear here when ready.', 'status')
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) pushLine('audio_director', 'Nolan could not start this audio take. Please try again.', 'error')
    } finally {
      finishWorkflow(runId)
    }
  }

  async function doEpisodeFeedback(episodeNumber: number, action: 'revise' | 'continue', feedbackOverride?: EpisodeFeedback) {
    const feedback = feedbackOverride || episodeFeedback[episodeNumber] || { keep: '', change_this_episode: '', next_direction: '' }
    if (action === 'revise' && !feedback.change_this_episode.trim()) {
      pushLine('director', 'Tell Nolan what should change in this episode first.', 'error')
      return
    }
    const runId = beginWorkflow()
    try {
      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({
        role: 'Story director',
        text: action === 'revise'
          ? `Reworking Episode ${episodeNumber} without losing what you asked to keep.`
          : episodeNumber === 3
            ? 'Checking that the ending lands before the story is complete.'
            : `Locking Episode ${episodeNumber}'s choices and carrying them into the next episode.`,
        color: 'purple',
      })
      await api.submitEpisodeFeedback(sessionId, episodeNumber, action, feedback)
      setEpisodeFeedback(previous => ({ ...previous, [episodeNumber]: feedback }))
      const settled = await pollForSeries(runId, saved => {
        const current = saved.episodes?.find((item: StoryEpisode) => item.number === episodeNumber)
        if (action === 'revise') return current?.status === 'DRAFT_READY'
        if (episodeNumber === 3) return current?.status === 'APPROVED'
        return current?.status === 'APPROVED' && saved.episodes?.some((item: StoryEpisode) => item.number === episodeNumber + 1 && item.status === 'DRAFT_READY')
      })
      if (!settled && isWorkflowActive(runId)) pushLine('director', 'Nolan is still carrying your notes forward. Please refresh in a moment.', 'error')
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) pushLine('director', 'Nolan could not apply that note yet. Please try again.', 'error')
    } finally {
      finishWorkflow(runId)
    }
  }

  async function applyConstitutionRepair(check: Check) {
    const repair = check.repair?.trim()
    if (!repair || busy) return

    if (!seriesPlan) {
      await doRevise(repair)
      return
    }

    const episode = episodeByNumber(activeEpisodeNumber)
    if (!episode?.production_script) {
      setEpisodeFeedback(previous => ({
        ...previous,
        [activeEpisodeNumber]: {
          ...(previous[activeEpisodeNumber] || { keep: '', change_this_episode: '', next_direction: '' }),
          change_this_episode: repair,
        },
      }))
      pushLine('supervisor', 'The suggested repair is ready in the episode notes. Draft the episode before applying it.', 'repair')
      return
    }

    if (seriesPlan) {
      const runId = beginWorkflow()
      try {
        const result = await api.applyConstitutionRepair(sessionId, activeEpisodeNumber, check.rule_number, repair)
        const repairedEpisode = result.episode as StoryEpisode
        setEpisodes(previous => previous.some(item => item.number === repairedEpisode.number)
          ? previous.map(item => item.number === repairedEpisode.number ? repairedEpisode : item)
          : [...previous, repairedEpisode])
        selectSeriesEpisode(repairedEpisode)
        setChecks(repairedEpisode.constitution_report?.checks || [])
        setScore(repairedEpisode.constitution_report?.overall_score ?? null)
        setScriptReady(Boolean(repairedEpisode.production_script))
        pushLine('supervisor', `✓ Rule ${check.rule_number} repaired immediately. The updated episode is ready to review.`, 'repair')
      } catch (error) {
        console.error(error)
        if (isWorkflowActive(runId)) pushLine('supervisor', 'The fast repair could not be applied. Please try again.', 'error')
      } finally {
        finishWorkflow(runId)
      }
      return
    }

    const feedback: EpisodeFeedback = {
      keep: 'Preserve every Constitution rule that already passed, plus all locked story details.',
      change_this_episode: repair,
      next_direction: '',
    }
    setEpisodeFeedback(previous => ({ ...previous, [activeEpisodeNumber]: feedback }))
    await doEpisodeFeedback(activeEpisodeNumber, 'revise', feedback)
  }

  async function doProduce() {
    if (!selectedVision) return
    const runId = beginWorkflow()
    setStep('production')
    setAudioUrl(null)
    setCoverImageUrl(null)
    setAudioError('')
    let savingPreferences = true
    try {
      await api.updatePreferences(sessionId, requestedLanguage, voiceCast, seriesFormat)
      savingPreferences = false
      if (!isWorkflowActive(runId)) return

      setSseUrl(api.eventsUrl(sessionId))
      setStudioUpdate({ role: 'Writer', text: 'Turning your chosen treatment into an audio-native pilot.', color: 'blue' })
      pushLine('writer', 'Turning your chosen story into an episode…')
      await api.produce(sessionId, {
        primary_vision_id: selectedVision,
        opening_from: selectedVision,
        relationship_from: selectedVision,
        ending_from: selectedVision,
      })

      const result = await pollForAudioResult(runId, 20)
      if (!isWorkflowActive(runId)) return
      if (result === 'error') {
        pushLine('director', 'The episode could not finish. Your story is still safe—please try again.', 'error')
      } else if (result === 'timeout') {
        pushLine('director', 'The episode is taking longer than expected. You can try again when you are ready.', 'error')
      }
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) {
        pushLine(
          'director',
          savingPreferences
            ? 'Your voice settings could not be saved. Please try again.'
            : 'Nolan could not start this episode. Please try again.',
          'error',
        )
      }
    } finally {
      finishWorkflow(runId)
    }
  }

  async function doRevise(changeOverride?: string) {
    const changeInstruction = (changeOverride ?? revise).trim()
    if (!changeInstruction) return
    const runId = beginWorkflow()
    setLockDiff(null)
    setAudioUrl(null)
    setCoverImageUrl(null)
    setAudioError('')
    try {
      setSseUrl(api.eventsUrl(sessionId))
      pushLine('supervisor', `Updating your story: "${changeInstruction.slice(0, 60)}"`)
      await api.revise(sessionId, changeInstruction, Array.from(lockedFields))
      setRevise('')

      const result = await pollForAudioResult(runId, 15)
      if (!isWorkflowActive(runId)) return
      if (result === 'error') {
        pushLine('supervisor', 'The revision could not finish. Your approved script is still safe.', 'error')
      } else if (result === 'timeout') {
        pushLine('supervisor', 'The revision is taking longer than expected. You can try again when you are ready.', 'error')
      }
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) {
        pushLine('supervisor', 'The revision could not be started. Please try again.', 'error')
      }
    } finally {
      finishWorkflow(runId)
    }
  }

  async function doPlanVisualEpisode() {
    if (seriesFormat !== 'video' || !videoSourcesSaved) {
      setVisualError('Save both source videos before planning the video cut.')
      return
    }
    setBusy(true)
    setVisualError('')
    try {
      setVisualPlan(await api.planVisualEpisode(sessionId, false, true, activeEpisodeNumber))
      await refreshSession()
    } catch (error) {
      console.error(error)
      setVisualError('Nolan could not plan this video cut. Please try again.')
    } finally { setBusy(false) }
  }

  async function doRenderVideoTeaser() {
    if (!visualPlan) {
      setVisualError('Plan the visual version first.')
      return
    }
    setBusy(true)
    setVisualError('')
    try {
      setSseUrl(api.eventsUrl(sessionId))
      const result = await api.renderVideoTeaser(sessionId, seriesPlan ? activeEpisodeNumber : undefined)
      setVisualResult(result)
      pushLine('visual_director', 'Cutting both source videos to the final audio master length.')
    } catch (error) {
      console.error(error)
      setVisualError('Nolan could not build the video cut. Check that both source videos are still available and try again.')
    } finally {
      setBusy(false)
    }
  }

  async function doComposeEpisodeVideo() {
    setBusy(true)
    setVisualError('')
    try {
      const result = await api.composeEpisodeVideo(sessionId, seriesPlan ? activeEpisodeNumber : undefined)
      setVisualResult(result)
    } catch (error) {
      console.error(error)
      setVisualError('Nolan could not package this scene with the episode audio. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function doGenerateCover() {
    setCoverGenerating(true)
    setCoverError('')
    try {
      const result = await api.generateCoverImage(sessionId, seriesPlan ? activeEpisodeNumber : undefined, posterPrompt)
      setCoverImageUrl(api.absoluteUrl(result.url))
      setCoverIsFallback(!result.generated)
    } catch (error) {
      console.error(error)
      setCoverError('Nolan could not create the cover. Please try again.')
    } finally {
      setCoverGenerating(false)
    }
  }

  async function saveScreenplay() {
    if (!scriptDraft || !seriesPlan) return
    setBusy(true)
    setScriptSaveError('')
    try {
      const result = await api.updateEpisodeScript(sessionId, activeEpisodeNumber, scriptDraft)
      const updated = result.episode as StoryEpisode
      setEpisodes(previous => previous.map(item => item.number === updated.number ? updated : item))
      setChecks(updated.constitution_report?.checks || [])
      setScore(updated.constitution_report?.overall_score ?? null)
      setScriptEditMode(false)
      setCoverImageUrl(null)
      pushLine('writer', `Episode ${activeEpisodeNumber} screenplay saved. Its next audio take will use these dialogue, SFX, and pause cues.`, 'complete')
    } catch (error) {
      console.error(error)
      setScriptSaveError('The screenplay could not be saved. Please try again.')
    } finally { setBusy(false) }
  }

  async function doSavePosterReference() {
    if (!posterReferenceFile || !posterReferenceConsent) {
      setPosterReferenceError('Choose an image and confirm that you can use it.')
      return
    }
    if (posterReferenceFile.size > 5 * 1024 * 1024) {
      setPosterReferenceError('Use an image under 5 MB for a fast poster render.')
      return
    }
    setPosterReferenceError('')
    setCoverGenerating(true)
    try {
      const asset = await api.uploadPosterReference(sessionId, posterReferenceFile, true)
      setStoryAssets(previous => [...previous.filter(item => !item.filename.startsWith('poster-reference-')), asset])
      setPosterReferenceSaved(true)
      setPosterReferenceFile(null)
      setPosterReferenceConsent(false)
      pushLine('visual_director', 'Poster reference saved. Nolan will use its mood and composition for the next cover.', 'complete')
    } catch (error) {
      console.error(error)
      setPosterReferenceError('Nolan could not save that reference image. Please try again.')
    } finally {
      setCoverGenerating(false)
    }
  }

  async function startCameoRecording() {
    if (!cameoConsent) {
      setCameoRecorderError('Please confirm that this is your voice before recording.')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setCameoRecorderError('This browser cannot record audio here. Try a current browser with microphone access.')
      return
    }

    setCameoRecorderError('')
    setCameoStatus('')
    setCameoFile(null)
    setCameoSeconds(0)

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find(type => MediaRecorder.isTypeSupported(type))
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      const chunks: Blob[] = []
      const startedAt = Date.now()
      let recorderHadError = false

      cameoStreamRef.current = stream
      cameoRecorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (event.data.size > 0) chunks.push(event.data)
      }
      recorder.onerror = () => {
        recorderHadError = true
        setCameoRecorderError('The recording stopped unexpectedly. Please try again.')
      }
      recorder.onstop = () => {
        clearCameoTimer()
        releaseCameoMicrophone()
        cameoRecorderRef.current = null
        setCameoRecording(false)

        if (recorderHadError) return
        const recordedType = recorder.mimeType || mimeType || 'audio/webm'
        const sample = new Blob(chunks, { type: recordedType })
        if (sample.size === 0) {
          setCameoRecorderError('No audio was captured. Please check your microphone and try again.')
          return
        }

        const extension = recordedType.includes('mp4') ? 'm4a' : 'webm'
        const duration = Math.max(1, Math.min(CAMEO_MAX_SECONDS, Math.floor((Date.now() - startedAt) / 1000)))
        setCameoSeconds(duration)
        setCameoFile(new File([sample], `cameo-sample.${extension}`, { type: recordedType }))
        setCameoStatus(`Recording ready (${formatRecordingTime(duration)}). You can now create your temporary clone.`)
      }

      recorder.start(1000)
      setCameoRecording(true)
      setCameoStatus('Recording… Read the sample aloud in a calm, natural voice.')
      cameoTimerRef.current = window.setInterval(() => {
        const elapsed = Math.min(CAMEO_MAX_SECONDS, Math.floor((Date.now() - startedAt) / 1000))
        setCameoSeconds(elapsed)
        if (elapsed >= CAMEO_MAX_SECONDS) {
          clearCameoTimer()
          if (recorder.state !== 'inactive') recorder.stop()
        }
      }, 250)
    } catch (error) {
      console.error(error)
      clearCameoTimer()
      releaseCameoMicrophone()
      cameoRecorderRef.current = null
      setCameoRecording(false)
      setCameoRecorderError('Microphone access was not available. Allow it in your browser and try again.')
    }
  }

  function stopCameoRecording() {
    const recorder = cameoRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    clearCameoTimer()
    setCameoStatus('Finishing your recording…')
    recorder.stop()
  }

  async function doCloneVoice() {
    if (!cameoFile || !cameoConsent || cameoRecording) return
    const characterName = cameoRole === 'character'
      ? cameoCharacterName || dna?.protagonist.name || null
      : null
    const targetLabel = cameoRole === 'narrator' ? 'Narrator' : characterName || 'the selected character'
    setBusy(true)
    setCameoStatus('Recording consent and uploading voice sample...')
    try {
      await api.recordVoiceConsent(sessionId, {
        confirmed: true,
        assigned_to: cameoRole,
        character_name: characterName,
      })
      // Upload voice sample
      const fd = new FormData()
      fd.append('audio', cameoFile, cameoFile.name)
      const res = await api.cloneVoice(sessionId, fd)
      if (res.success) {
        const targetKey = cameoRole === 'narrator' ? 'NARRATOR' : (characterName || '').toUpperCase()
        if (res.voice_id && targetKey) {
          setVoiceCast(previous => ({ ...previous, [targetKey]: `voice:${res.voice_id}` }))
          setVoiceOptions(previous => previous.some(voice => voice.voice_id === res.voice_id)
            ? previous
            : [...previous, { voice_id: res.voice_id, name: 'My voice', gender: '', category: 'cloned' }])
        }
        setCameoStatus(`✓ Voice cloned successfully! Your voice will play ${targetLabel} in this episode.`)
        pushLine('audio_director', `Voice Cameo cloned — your voice will play ${targetLabel}.`, 'complete')
      } else if (res.requires_verification) {
        setCameoStatus('Your voice needs verification. Use the voice you selected for now.')
      } else if (res.requires_upgrade) {
        setCameoStatus('Voice cloning needs an ElevenLabs Starter plan or above. Your story can still use the voice you selected.')
      } else {
        setCameoStatus('Voice cloning could not start. Your story can still use the voice you selected.')
      }
    } catch (err) {
      console.error(err)
      setCameoStatus('Voice cloning could not start. Your story can still use the voice you selected.')
    } finally {
      setBusy(false)
      setCameoFile(null)
    }
  }

  function toggleLock(field: string) {
    const nextLocks = new Set(lockedFields)
    nextLocks.has(field) ? nextLocks.delete(field) : nextLocks.add(field)
    const locked_fields = Array.from(nextLocks)
    setLockedFields(nextLocks)
    setDna(current => current ? { ...current, locked_fields } : current)
    if (dna) {
      void api.updateDNA(sessionId, { ...dna, locked_fields }).catch(error => {
        console.error(error)
        pushLine('director', 'Your lock could not be saved yet. It is still active in this session.', 'error')
      })
    }
  }

  async function doRetryAudio() {
    if (!scriptReady) return
    const runId = beginWorkflow()
    setAudioError('')
    setAudioUrl(null)
    setStep('production')
    setSseUrl(api.eventsUrl(sessionId))
    setStudioUpdate({ role: 'Audio Director', text: 'Casting the voices and mixing the episode.', color: 'gold' })
    pushLine('audio_director', 'Creating a fresh audio take from your approved script…')
    try {
      await api.renderAudio(sessionId)
      const result = await pollForAudioResult(runId, 20)
      if (!isWorkflowActive(runId)) return
      if (result === 'error') {
        setAudioError('The audio take could not be completed. Your story is still safe—please try again.')
        pushLine('audio_director', 'The audio take could not be completed. Please try again.', 'error')
      } else if (result === 'timeout') {
        setAudioError('The audio take is taking longer than expected. Please try the render again.')
        pushLine('audio_director', 'The audio take is taking longer than expected. Please try again.', 'error')
      }
    } catch (error) {
      console.error(error)
      if (isWorkflowActive(runId)) {
        setAudioError('The audio room could not be reached. Your story is still safe—please try the render again.')
        pushLine('audio_director', 'The audio room could not be reached. Please try the render again.', 'error')
      }
    } finally {
      finishWorkflow(runId)
    }
  }

  const currentStepIdx = STEPS.findIndex(s => s.id === step)
  const currentEpisode = episodeByNumber(activeEpisodeNumber)
  const posterTitle = currentEpisode?.production_script?.title || currentEpisode?.outline.title || seriesPlan?.title || dna?.protagonist.name || 'Nolan Original'
  const posterCast = dna
    ? [dna.protagonist.name, ...(dna.characters || []).filter(character => character.name !== dna.protagonist.name).map(character => character.name)]
    : []
  const voiceCastNames = dna
    ? Array.from(new Map(['Narrator', dna.protagonist.name, ...(dna.characters || []).map(c => c.name)]
      .filter(Boolean)
      .map(name => [name.toUpperCase(), name])).values())
    : []
  const cameoTargetKey = cameoRole === 'narrator' ? 'Narrator' : cameoCharacterName || ''
  const cameoTargetLabel = cameoRole === 'narrator'
    ? 'Narrator'
    : cameoCharacterName || dna?.protagonist.name || 'the selected character'
  const cameoSampleScript = CAMEO_SAMPLE_SCRIPTS[requestedLanguage.toLowerCase().split('-', 1)[0]] || CAMEO_SAMPLE_SCRIPTS.en
  const selectCameoTarget = (name: string) => {
    const isNarrator = name.toUpperCase() === 'NARRATOR'
    setCameoRole(isNarrator ? 'narrator' : 'character')
    setCameoCharacterName(isNarrator ? null : name)
    setCameoRecorderError('')
    setCameoStatus(`Selected target: ${isNarrator ? 'Narrator' : name}. Record or upload a sample to continue.`)
  }
  const isCameoTarget = (name: string) => Boolean(
    cameoRole === 'narrator'
      ? name.toUpperCase() === 'NARRATOR'
      : cameoCharacterName?.toUpperCase() === name.toUpperCase()
  )
  const castingChoice = (name: string) => {
    const choice = voiceCast[name.toUpperCase()]
    if (!choice) return 'auto:neutral'
    if (['feminine', 'masculine', 'neutral'].includes(choice)) return `auto:${choice}`
    return choice
  }

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Top Bar ── */}
      <header className="studio-header sticky top-0 z-30 border-b border-nolan-border/60 px-4 py-3 backdrop-blur-xl lg:px-7">
        <div className="mx-auto flex max-w-6xl items-center gap-4">
          <div className="flex shrink-0 items-center gap-2">
            <span className="nolan-mark" aria-hidden="true"><span /></span>
            <span className="font-bold text-sm tracking-[0.2em] text-white">NOLAN</span>
          </div>

          <div className="creation-pipeline min-w-0 flex-1">
          {STEPS.map((s, i) => {
            const done = i < currentStepIdx
            const active = i === currentStepIdx
            return (
              <div key={s.id} className="pipeline-stage">
                <div className={`pipeline-dot ${done ? 'is-done' : active ? 'is-active' : ''}`}>
                  {done ? <CheckCircle className="w-3.5 h-3.5" /> : <s.icon className="w-3.5 h-3.5" />}
                </div>
                <span className={`pipeline-label ${active ? 'is-active' : done ? 'is-done' : ''}`}>{s.label}</span>
                {i < STEPS.length - 1 && <span className={`pipeline-line ${i < currentStepIdx ? 'is-done' : ''}`} />}
              </div>
            )
          })}
        </div>

          <button type="button" onClick={() => setJarvisOpen(true)} className="jarvis-trigger shrink-0" aria-label="Open director's reel">
            <span className="jarvis-core"><CircleDot className="w-5 h-5" /></span>
            <span className="hidden text-[10px] font-semibold tracking-[0.12em] text-nolan-accent md:inline">REEL</span>
            {busy && <span className="jarvis-live" />}
          </button>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex-1 min-w-0">

        <main className="studio-workspace mx-auto flex w-full max-w-7xl flex-col gap-5 p-4 sm:p-8">

          {!dna && !busy && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass rounded-2xl p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-nolan-accent">Nolan heard this</p>
              <h1 className="text-2xl font-bold text-white mt-2">Is this your story?</h1>
              <p className="text-sm text-nolan-muted mt-1">Edit anything before Nolan creates the people, world, genre, and episode.</p>
              <textarea value={transcriptDraft} onChange={e => setTranscriptDraft(e.target.value)} rows={6}
                className="w-full mt-4 bg-black/20 border border-nolan-border rounded-xl p-4 text-sm text-white resize-none focus:outline-none focus:border-nolan-accent" />
              <div className="grid sm:grid-cols-2 gap-2 mt-3">
                <input value={protagonistHint} onChange={e => setProtagonistHint(e.target.value)} placeholder="Main character name (optional)"
                  className="bg-black/20 border border-nolan-border rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-nolan-muted/50 focus:outline-none focus:border-nolan-accent" />
                <input value={characterHints} onChange={e => setCharacterHints(e.target.value)} placeholder="Other people to include (optional)"
                  className="bg-black/20 border border-nolan-border rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-nolan-muted/50 focus:outline-none focus:border-nolan-accent" />
              </div>
              {storyError && <p className="mt-3 text-xs text-red-300">{storyError}</p>}
              <button onClick={() => setStoryApproved(true)} disabled={!transcriptDraft.trim()}
                className="w-full mt-3 py-3 bg-nolan-accent text-white rounded-xl font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-40">
                <Sparkles className="w-4 h-4" /> Yes — build my story
              </button>
            </motion.section>
          )}

          {!dna && busy && <div className="glass rounded-2xl p-7 space-y-4">
            <div className="flex items-center gap-3"><Loader2 className="w-6 h-6 text-nolan-accent animate-spin" /><div><p className="text-white font-semibold">Your story room is working</p><p className="text-xs text-nolan-muted">Voice and sound design can take a minute.</p></div></div>
            <StudioNote role={studioUpdate.role} text={studioUpdate.text} color={studioUpdate.color} />
          </div>}

          {/* ── STEP 1: Creative DNA ── */}
          {dna && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Sparkles className="w-4 h-4 text-purple-400" />} label="Nolan heard your story" badge="Choose what stays" />
              <div className="glass rounded-2xl p-5 mt-2 overflow-hidden relative">
                <div className="absolute -right-12 -top-12 w-40 h-40 bg-nolan-accent/20 blur-3xl rounded-full" />
                <p className="text-[11px] uppercase tracking-[0.2em] text-nolan-accent mb-2">Your main character</p>
                <h1 className="text-3xl font-bold text-white">{dna.protagonist.name}</h1>
                <p className="text-nolan-muted text-sm mt-1">Wants to {dna.protagonist.desire} — but fears {dna.protagonist.fear}.</p>
                <div className="flex gap-2 flex-wrap mt-3">{(dna.genre || []).map((g: string) => <Tag key={g} text={g} color="purple" />)}{(dna.story_references || []).map((r: string) => <Tag key={r} text={`inspired by ${r}`} color="default" />)}</div>

                <div className="mt-4 space-y-0">
                  <DNARow label="Core emotion" value={dna.core_emotion} field="core_emotion" locked={lockedFields} onToggle={toggleLock} />
                  <DNARow label="Central conflict" value={dna.central_conflict} field="central_conflict" locked={lockedFields} onToggle={toggleLock} />
                  <DNARow label="What listeners should feel" value={dna.audience_promise} field="audience_promise" locked={lockedFields} onToggle={toggleLock} />
                  <DNARow label="Protagonist desire" value={dna.protagonist.desire} field="protagonist.desire" locked={lockedFields} onToggle={toggleLock} />
                  <DNARow label="Protagonist fear" value={dna.protagonist.fear} field="protagonist.fear" locked={lockedFields} onToggle={toggleLock} />
                </div>

                {(dna.characters || []).length > 1 && <div className="mt-4"><p className="text-[10px] uppercase tracking-widest text-nolan-muted mb-2">The people in this episode</p><div className="grid sm:grid-cols-2 gap-2">{(dna.characters || []).filter((c: any) => c.name !== dna.protagonist.name).map((c: any) => <div key={c.name} className="rounded-xl bg-black/20 p-3"><p className="text-sm text-white">{c.name} <span className="text-nolan-muted">· {c.role}</span></p><p className="text-[11px] text-nolan-muted mt-1">{c.relationship_to_protagonist} — {c.secret_or_tension}</p></div>)}</div></div>}
                <p className="text-xs text-nolan-gold mt-4">Keep these details: {dna.non_negotiables.join(' · ')}</p>
                <div className="flex gap-2 flex-wrap pt-3">{dna.tone.map(t => <Tag key={t} text={t} color="purple" />)}{dna.symbols.map(s => <Tag key={s} text={s} color="default" />)}</div>
              </div>
              <div className="glass rounded-xl p-4 mt-3 border border-nolan-accent/30">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-white">Choose your series format</p>
                    <p className="text-[11px] text-nolan-muted mt-1">This decides what Nolan is allowed to produce after the story is approved.</p>
                  </div>
                  <span className="rounded-full bg-nolan-surface px-2 py-1 text-[10px] text-nolan-muted">{seriesFormat === 'audio' ? 'Audio-only' : 'Video + audio'}</span>
                </div>
                <div className="grid sm:grid-cols-2 gap-2 mt-3">
                  <button type="button" onClick={() => chooseSeriesFormat('audio')} disabled={busy}
                    className={`rounded-xl border p-3 text-left transition-all ${seriesFormat === 'audio' ? 'border-nolan-accent bg-nolan-accent/10' : 'border-nolan-border/60 bg-black/10 hover:border-nolan-accent/50'}`}>
                    <div className="flex items-center gap-2"><Volume2 className="w-4 h-4 text-nolan-accent" /><span className="text-xs font-semibold text-white">Audio series</span></div>
                    <p className="text-[10px] leading-4 text-nolan-muted mt-2">A podcast-style episode with a generated poster and no visual uploads.</p>
                    <p className="text-[10px] text-nolan-green mt-2">✓ Minimum 60-second audio master</p>
                  </button>
                  <button type="button" onClick={() => chooseSeriesFormat('video')} disabled={busy}
                    className={`rounded-xl border p-3 text-left transition-all ${seriesFormat === 'video' ? 'border-pink-300 bg-pink-300/10' : 'border-nolan-border/60 bg-black/10 hover:border-pink-300/50'}`}>
                    <div className="flex items-center gap-2"><Film className="w-4 h-4 text-pink-200" /><span className="text-xs font-semibold text-white">Video series</span></div>
                    <p className="text-[10px] leading-4 text-nolan-muted mt-2">A cut using both of your source videos, synced to the final audio length.</p>
                    <p className="text-[10px] text-pink-200 mt-2">Two videos required before render</p>
                  </button>
                </div>
                {seriesFormat === 'audio' ? (
                  <div className="mt-3 rounded-lg bg-nolan-surface/70 px-3 py-2 text-[10px] leading-4 text-nolan-muted">
                    Your finished episode will feel like a premium audio show: rotating album art, rich sound design, and a dynamically written poster.
                  </div>
                ) : (
                  <div className="mt-3 rounded-lg border border-pink-300/20 bg-pink-300/5 p-3">
                    <p className="text-[10px] uppercase tracking-widest text-pink-200">Two source videos</p>
                    <p className="mt-1 text-[10px] leading-4 text-nolan-muted">Upload both clips. Nolan uses them as editorial footage and cuts the finished video to the audio master — no image uploads, no missing source footage.</p>
                    <div className="grid sm:grid-cols-2 gap-2 mt-3">
                      <label className="rounded-lg border border-nolan-border/70 bg-black/20 p-3 text-[10px] text-nolan-muted cursor-pointer hover:border-pink-300/60">
                        <span className="block text-xs font-semibold text-white">Source video 01</span>
                        <span className="block mt-1 truncate">{videoFileOne?.name || 'Choose a video file'}</span>
                        <input type="file" accept="video/*" className="hidden" disabled={busy} onChange={event => { setVideoFileOne(event.target.files?.[0] || null); setVideoSourcesSaved(false); setVideoUploadError('') }} />
                      </label>
                      <label className="rounded-lg border border-nolan-border/70 bg-black/20 p-3 text-[10px] text-nolan-muted cursor-pointer hover:border-pink-300/60">
                        <span className="block text-xs font-semibold text-white">Source video 02</span>
                        <span className="block mt-1 truncate">{videoFileTwo?.name || 'Choose a video file'}</span>
                        <input type="file" accept="video/*" className="hidden" disabled={busy} onChange={event => { setVideoFileTwo(event.target.files?.[0] || null); setVideoSourcesSaved(false); setVideoUploadError('') }} />
                      </label>
                    </div>
                    <label className="mt-3 flex items-start gap-2 text-[10px] text-nolan-muted"><input type="checkbox" checked={videoConsent} disabled={busy} onChange={event => setVideoConsent(event.target.checked)} className="mt-0.5" />I own both videos or have permission to use them in this series.</label>
                    <button type="button" onClick={doSaveVideoSources} disabled={busy || !videoFileOne || !videoFileTwo || !videoConsent} className="mt-3 w-full rounded-lg bg-pink-300 py-2 text-[11px] font-semibold text-slate-950 hover:bg-pink-200 disabled:opacity-40 flex items-center justify-center gap-2">
                      {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}{videoSourcesSaved ? 'Both videos saved' : 'Save both source videos'}
                    </button>
                    {videoSourcesSaved && <p className="mt-2 text-center text-[10px] text-nolan-green">✓ Both videos are ready. The video render stays locked until the audio master exists.</p>}
                    {videoUploadError && <p className="mt-2 text-[10px] text-red-300">{videoUploadError}</p>}
                  </div>
                )}
              </div>
              <div className="glass rounded-xl p-4 mt-3">
                <p className="text-xs font-semibold text-white">Choose the voices</p>
                <p className="text-[11px] text-nolan-muted mt-1">Pick a voice here. To use your own voice, record once below and choose who it plays.</p>
                <div className="grid sm:grid-cols-2 gap-2 mt-3">
                  {voiceCastNames.map(name => (
                    <div key={name} className="flex items-center justify-between gap-2 rounded-lg bg-black/20 px-3 py-2 text-xs text-white">
                      <div className="min-w-0">
                        <span className="block truncate">{name}</span>
                      </div>
                      <select value={castingChoice(name)}
                        onChange={e => setVoiceCast(prev => ({ ...prev, [name.toUpperCase()]: e.target.value }))}
                        className="bg-nolan-surface border border-nolan-border rounded px-2 py-1 text-xs text-white">
                        <option value="auto:neutral">Nolan chooses · neutral</option>
                        <option value="auto:feminine">Nolan chooses · feminine</option>
                        <option value="auto:masculine">Nolan chooses · masculine</option>
                        {voiceOptions.length > 0 && <optgroup label="My saved voices">
                          {voiceOptions.map(voice => <option key={voice.voice_id} value={`voice:${voice.voice_id}`}>
                            {voice.name}{voice.gender ? ` · ${voice.gender}` : ''}
                          </option>)}
                        </optgroup>}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
              {/* Voice Cameo */}
              <div className="glass rounded-xl p-4 mt-3 border border-nolan-accent/20">
                <p className="text-xs font-semibold text-white flex items-center gap-2"><Mic className="w-3.5 h-3.5 text-nolan-accent" /> Voice Cameo (optional)</p>
                <p className="text-[11px] text-nolan-muted mt-1">Record or upload a clean 10-second sample to perform as the person you selected above.</p>
                <div className="flex items-center gap-2 mt-2">
                  <label className="flex items-start gap-1.5 text-xs text-nolan-muted">
                    <input type="checkbox" checked={cameoConsent} disabled={cameoRecording} onChange={e => setCameoConsent(e.target.checked)} className="rounded mt-0.5" />
                    I confirm this is my voice and I consent to Nolan creating a temporary clone for this session.
                  </label>
                </div>
                <div className="mt-3 rounded-lg bg-black/20 border border-nolan-border/60 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-widest text-nolan-muted">Your voice will play</p>
                  <div className="mt-1 flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold text-white">{cameoTargetLabel}</span>
                    <select value={cameoTargetKey} disabled={cameoRecording} onChange={e => selectCameoTarget(e.target.value)}
                      className="bg-nolan-surface border border-nolan-border rounded px-2 py-1 text-xs text-white">
                      {voiceCastNames.map(name => <option key={name} value={name}>{name}</option>)}
                    </select>
                </div>
                </div>
                {cameoRecording && (
                  <div className="rounded-lg border border-nolan-border/60 bg-black/20 p-3 mt-3">
                    <p className="text-[10px] uppercase tracking-widest text-nolan-accent mb-2">Read this aloud</p>
                    <p className="text-[11px] leading-5 text-nolan-text">{cameoSampleScript}</p>
                  </div>
                )}
                <div className="flex items-center justify-between gap-3 mt-3">
                  <span className={`text-[11px] ${cameoRecording ? 'text-red-300' : cameoFile ? 'text-nolan-accent' : 'text-nolan-muted'}`}>
                    {cameoRecording ? `● Recording ${formatRecordingTime(cameoSeconds)} / ${formatRecordingTime(CAMEO_MAX_SECONDS)}` : cameoFile ? `✓ Sample ready${cameoSeconds ? ` · ${formatRecordingTime(cameoSeconds)}` : ''}` : '10 seconds is enough'}
                  </span>
                  <div className="flex items-center gap-2">
                    <label className={`shrink-0 py-1.5 px-3 rounded-lg border border-nolan-border text-xs text-nolan-muted hover:text-white cursor-pointer ${cameoRecording ? 'opacity-40 pointer-events-none' : ''}`}>
                      <Upload className="w-3 h-3 inline mr-1.5" /> Upload sample
                      <input type="file" accept="audio/*" className="hidden" disabled={cameoRecording} onChange={event => {
                        const file = event.target.files?.[0] || null
                        setCameoFile(file)
                        setCameoSeconds(0)
                        setCameoRecorderError('')
                        setCameoStatus(file ? 'Upload ready. You can now create your temporary clone.' : '')
                      }} />
                    </label>
                    <button type="button" onClick={cameoRecording ? stopCameoRecording : startCameoRecording} disabled={busy || (!cameoRecording && !cameoConsent)}
                      className={`shrink-0 py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 disabled:opacity-40 ${cameoRecording ? 'bg-red-500/80 text-white hover:bg-red-500' : 'bg-nolan-accent/80 text-white hover:bg-nolan-accent'}`}>
                      {cameoRecording ? <><XCircle className="w-3 h-3" /> Stop</> : <><Mic className="w-3 h-3" /> Record</>}
                    </button>
                  </div>
                </div>
                {!cameoConsent && <p className="text-[10px] text-nolan-muted mt-2">Confirm consent to enable recording.</p>}
                {cameoRecorderError && <p className="text-[10px] text-red-300 mt-2">{cameoRecorderError}</p>}
                {cameoConsent && cameoFile && !cameoRecording && (
                  <button type="button" onClick={doCloneVoice} disabled={busy}
                    className="mt-2 w-full py-1.5 bg-nolan-accent/80 text-white rounded-lg text-xs font-semibold hover:bg-nolan-accent disabled:opacity-40 flex items-center justify-center gap-2">
                    <Mic className="w-3 h-3" /> Use my voice
                  </button>
                )}
                {cameoStatus && <p className="text-[10px] text-nolan-muted mt-2">{cameoStatus}</p>}
              </div>
              {step === 'visions' && visions.length === 0 && (
                <button onClick={doGenerateVisions} disabled={busy}
                  className="mt-3 w-full py-2.5 bg-nolan-accent text-white rounded-xl text-sm font-semibold hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2">
                  <GitBranch className="w-4 h-4" /> Show me three story directions
                </button>
              )}
            </motion.section>
          )}

          {/* ── STEP 2: Visions ── */}
          {visions.length > 0 && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<GitBranch className="w-4 h-4 text-blue-400" />} label="Choose your story direction" badge="Pick the path that feels most like your story" />
              <div className="space-y-3 mt-2">
                {visions.map(v => (
                  <VisionCard key={v.id} vision={v} selected={selectedVision === v.id}
                    onSelect={() => setSelectedVision(v.id)} />
                ))}
              </div>
              {selectedVision && (
                <button onClick={doCreateSeries} disabled={busy}
                  className="mt-3 w-full py-2.5 bg-nolan-accent text-white rounded-xl text-sm font-semibold hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2">
                  <Wand2 className="w-4 h-4" /> Plan my complete 3-part story
                </button>
              )}
            </motion.section>
          )}

          {/* ── Three-episode story ── */}
          {seriesPlan && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Film className="w-4 h-4 text-pink-300" />} label="Your 3-part story" badge="Plan first · make one at a time" />
              <div className="glass rounded-2xl p-5 mt-2 border border-pink-300/20">
                <p className="text-[10px] uppercase tracking-[0.18em] text-pink-200">The full promise</p>
                <h2 className="text-xl font-bold text-white mt-1">{seriesPlan.title}</h2>
                <p className="text-xs leading-5 text-nolan-muted mt-2">{seriesPlan.logline}</p>
                <div className="flex flex-wrap gap-2 mt-3">
                  <Tag text={seriesPlan.tone} color="purple" />
                  <Tag text={seriesPlan.ending_promise} color="default" />
                </div>
              </div>

              <div className="space-y-3 mt-3">
                {seriesPlan.episode_outlines.map(outline => {
                  const episode = episodeByNumber(outline.number)
                  const status = episode?.status || 'OUTLINED'
                  const prior = outline.number > 1 ? episodeByNumber(outline.number - 1) : null
                  const canDraft = outline.number === 1 || prior?.status === 'APPROVED'
                  const feedback = episodeFeedback[outline.number] || episode?.feedback || { keep: '', change_this_episode: '', next_direction: '' }
                  const active = activeEpisodeNumber === outline.number
                  return (
                    <div key={outline.number} className={`glass rounded-xl p-4 border transition-colors ${active ? 'border-nolan-accent/60' : 'border-nolan-border/40'}`}>
                      <button type="button" onClick={() => episode && selectSeriesEpisode(episode)} className="w-full text-left">
                        <div className="flex items-start gap-3">
                          <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${status === 'APPROVED' ? 'bg-nolan-green/20 text-nolan-green' : status === 'READY' ? 'bg-nolan-accent/20 text-nolan-accent' : 'bg-nolan-surface text-nolan-muted'}`}>
                            {status === 'APPROVED' ? <CheckCircle className="w-4 h-4" /> : outline.number}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-sm font-semibold text-white">Episode {outline.number}: {outline.title}</p>
                              <EpisodeStatusPill status={status} />
                            </div>
                            <p className="mt-1 text-xs leading-5 text-nolan-muted">{outline.what_happens}</p>
                          </div>
                        </div>
                      </button>
                      <div className="ml-10 mt-3 rounded-lg bg-black/20 p-3">
                        <p className="text-[10px] uppercase tracking-widest text-nolan-muted">The turn</p>
                        <p className="mt-1 text-xs text-nolan-text">{outline.emotional_turn}</p>
                        <p className="mt-2 text-[10px] uppercase tracking-widest text-nolan-muted">What this episode must land</p>
                        <p className="mt-1 text-xs text-nolan-text">{outline.ending_promise}</p>
                      </div>

                      {(status === 'OUTLINED' || status === 'STALE') && (
                        <div className="ml-10 mt-3">
                          {canDraft ? (
                            <button onClick={() => doDraftEpisode(outline.number)} disabled={busy}
                              className="w-full rounded-lg border border-nolan-accent/60 py-2 text-xs font-semibold text-nolan-accent hover:bg-nolan-accent/10 disabled:opacity-40">
                              {status === 'STALE' ? 'Refresh this episode from the new direction' : `Draft Episode ${outline.number}`}
                            </button>
                          ) : <p className="text-[11px] text-nolan-muted">Approve the previous episode first, so this one can remember its choices.</p>}
                        </div>
                      )}

                      {status === 'DRAFT_READY' && (
                        <div className="ml-10 mt-3 rounded-lg border border-nolan-accent/25 bg-nolan-accent/5 p-3">
                          <p className="text-xs font-semibold text-white">Your draft is ready.</p>
                          <p className="mt-1 text-[11px] text-nolan-muted">It is checked before audio. Make the final ~90-second episode only when this feels right.</p>
                          <button onClick={() => doConfirmEpisode(outline.number)} disabled={busy}
                            className="mt-3 w-full rounded-lg bg-nolan-accent py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2">
                            <Volume2 className="w-3.5 h-3.5" /> Make Episode {outline.number}
                          </button>
                        </div>
                      )}

                      {(status === 'DRAFTING' || status === 'RENDERING' || status === 'REVISING') && (
                        <div className="ml-10 mt-3 flex items-center gap-2 text-[11px] text-nolan-accent"><Loader2 className="w-3.5 h-3.5 animate-spin" /> {status === 'DRAFTING' ? 'Writing this episode…' : status === 'RENDERING' ? 'Making the audio episode…' : 'Updating this episode…'}</div>
                      )}

                      {status === 'READY' && (
                        <div className="ml-10 mt-3 space-y-3">
                          {episode?.audio_url && <button onClick={() => selectSeriesEpisode(episode)} className="w-full rounded-lg border border-nolan-accent/50 py-2 text-xs font-semibold text-nolan-accent hover:bg-nolan-accent/10 flex items-center justify-center gap-2"><Play className="w-3.5 h-3.5" /> Listen to Episode {outline.number}</button>}
                          {episode?.actual_duration_seconds !== undefined && episode.actual_duration_seconds !== null && <p className={`text-center text-[11px] ${episode.actual_duration_seconds >= 80 && episode.actual_duration_seconds <= 100 ? 'text-nolan-green' : 'text-yellow-200'}`}>Final length: {formatPlaybackTime(episode.actual_duration_seconds)} {episode.actual_duration_seconds >= 80 && episode.actual_duration_seconds <= 100 ? '· right in the 90-second range' : '· use “Fix this episode” if you want it closer to 90 seconds'}</p>}
                          <div className="rounded-lg border border-nolan-border/60 bg-black/20 p-3">
                            <p className="text-xs font-semibold text-white">Your call before the next episode</p>
                            <p className="mt-1 text-[11px] text-nolan-muted">A quick note is enough. Nolan carries it forward and never rewrites an approved episode in secret.</p>
                            <textarea value={feedback.keep} onChange={event => setEpisodeFeedback(previous => ({ ...previous, [outline.number]: { ...feedback, keep: event.target.value } }))} rows={1}
                              placeholder="What should stay? (optional)" className="mt-3 w-full resize-none rounded-lg border border-nolan-border/70 bg-nolan-surface p-2 text-xs text-white placeholder:text-nolan-muted/50 focus:outline-none focus:border-nolan-accent" />
                            <textarea value={feedback.change_this_episode} onChange={event => setEpisodeFeedback(previous => ({ ...previous, [outline.number]: { ...feedback, change_this_episode: event.target.value } }))} rows={1}
                              placeholder="What should change in this episode?" className="mt-2 w-full resize-none rounded-lg border border-nolan-border/70 bg-nolan-surface p-2 text-xs text-white placeholder:text-nolan-muted/50 focus:outline-none focus:border-nolan-accent" />
                            <textarea value={feedback.next_direction} onChange={event => setEpisodeFeedback(previous => ({ ...previous, [outline.number]: { ...feedback, next_direction: event.target.value } }))} rows={1}
                              placeholder={outline.number === 3 ? 'Any final ending note? (optional)' : `Where should Episode ${outline.number + 1} go? (optional)`} className="mt-2 w-full resize-none rounded-lg border border-nolan-border/70 bg-nolan-surface p-2 text-xs text-white placeholder:text-nolan-muted/50 focus:outline-none focus:border-nolan-accent" />
                            <div className="mt-3 grid grid-cols-2 gap-2">
                              <button onClick={() => doEpisodeFeedback(outline.number, 'revise')} disabled={busy || !feedback.change_this_episode.trim()} className="rounded-lg border border-nolan-gold/60 py-2 text-xs font-semibold text-nolan-gold hover:bg-nolan-gold/10 disabled:opacity-30">Fix this episode</button>
                              <button onClick={() => doEpisodeFeedback(outline.number, 'continue')} disabled={busy} className="rounded-lg bg-nolan-accent py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-40">{outline.number === 3 ? 'Finish story' : `Approve & draft Episode ${outline.number + 1}`}</button>
                            </div>
                          </div>
                        </div>
                      )}

                      {status === 'APPROVED' && <p className="ml-10 mt-3 flex items-center gap-1.5 text-[11px] text-nolan-green"><CheckCircle className="w-3.5 h-3.5" /> Approved. Its choices are protected for the next episode.</p>}
                    </div>
                  )
                })}
              </div>

              <div className="episode-rail mt-5" aria-label="Episode library">
                {seriesPlan.episode_outlines.map(outline => {
                  const episode = episodeByNumber(outline.number)
                  const selected = outline.number === activeEpisodeNumber
                  const artwork = episode?.cover_image_url ? api.absoluteUrl(episode.cover_image_url) : ''
                  return <button key={`rail-${outline.number}`} type="button" onClick={() => episode && selectSeriesEpisode(episode)}
                    className={`episode-tile ${selected ? 'is-active' : ''}`} style={artwork ? { backgroundImage: `linear-gradient(0deg, rgba(3,10,20,.94), rgba(3,10,20,.15)), url(${artwork})` } : undefined}>
                    <span className="text-[10px] uppercase tracking-[0.18em] text-nolan-accent">Episode {outline.number}</span>
                    <strong className="mt-1 text-sm text-white">{outline.title}</strong>
                    <span className="mt-auto text-[10px] text-nolan-muted">{episode?.audio_url ? 'Ready to play' : episode?.status === 'DRAFT_READY' ? 'Screenplay ready' : 'Coming next'}</span>
                  </button>
                })}
              </div>

            </motion.section>
          )}

          {/* ── STEP 3: Constitution ── */}
          {(checks.length > 0 || Boolean(seriesPlan)) && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Shield className="w-4 h-4 text-yellow-400" />}
                label={seriesPlan ? `Pocket FM Story Constitution · Episode ${activeEpisodeNumber}` : 'Pocket FM Story Constitution'} badge={score !== null ? `${score}/100` : undefined} />
              <div className="glass rounded-xl p-4 mt-2">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <p className="text-[11px] text-nolan-muted">Eight real-time story gates. Failed rules show the evidence and a repair Nolan can apply.</p>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className="text-nolan-green">{checks.filter(check => check.passed).length} passed</span>
                    <span className="text-nolan-red">{checks.filter(check => !check.passed).length} flagged</span>
                    <span className="text-nolan-muted">{CONSTITUTION_RULES.length - checks.length} pending</span>
                  </div>
                </div>
                <div className="space-y-2">
                  {CONSTITUTION_RULES.map(rule => {
                    const check = checks.find(item => item.rule_number === rule.rule_number)
                    return check
                      ? <ConstitutionRow key={rule.rule_number} check={check} onRepair={applyConstitutionRepair} disabled={busy} />
                      : <ConstitutionPendingRow key={rule.rule_number} rule={rule} />
                  })}
                </div>
              </div>
            </motion.section>
          )}

          {seriesPlan && scriptDraft && (!audioUrl || audioEpisodeNumber !== activeEpisodeNumber) && (
            <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <SectionHeader icon={<Film className="w-4 h-4 text-nolan-gold" />} label={`Episode ${activeEpisodeNumber} screenplay`} badge="Editable before audio" />
              <ScreenplayPaper script={scriptDraft} editing={scriptEditMode} busy={busy} error={scriptSaveError}
                onEdit={() => setScriptEditMode(true)}
                onCancel={() => { const episode = episodeByNumber(activeEpisodeNumber); if (episode?.production_script) setScriptDraft(JSON.parse(JSON.stringify(episode.production_script))); setScriptEditMode(false) }}
                onChange={setScriptDraft} onSave={saveScreenplay} canGenerate={currentEpisode?.status === 'DRAFT_READY'} onGenerate={() => doConfirmEpisode(activeEpisodeNumber)} />
            </motion.section>
          )}

          {/* ── STEP 4: Audio Pilot ── */}
          {audioUrl && (
            <motion.section initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}>
              <SectionHeader icon={<Volume2 className="w-4 h-4 text-nolan-accent" />} label={seriesPlan ? `Episode ${audioEpisodeNumber || activeEpisodeNumber} audio` : 'Your audio story'} />
              <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
              {seriesPlan && scriptDraft && audioEpisodeNumber === activeEpisodeNumber && <ScreenplayPaper script={scriptDraft} editing={scriptEditMode} busy={busy} error={scriptSaveError}
                onEdit={() => setScriptEditMode(true)} onCancel={() => setScriptEditMode(false)} onChange={setScriptDraft} onSave={saveScreenplay} canGenerate={currentEpisode?.status === 'DRAFT_READY'} onGenerate={() => doConfirmEpisode(activeEpisodeNumber)} compact />}
              <div className="glass rounded-xl p-5 mt-2 border border-nolan-accent/30"
                style={{ boxShadow: '0 0 30px rgba(108,71,255,0.1)' }}>
                {seriesPlan && audioEpisodeNumber && audioEpisodeNumber !== activeEpisodeNumber && (
                  <p className="mb-4 rounded-lg border border-nolan-gold/20 bg-nolan-gold/5 px-3 py-2 text-[11px] text-nolan-gold">Episode {audioEpisodeNumber} stays available while Episode {activeEpisodeNumber} is being prepared.</p>
                )}
                <audio ref={audioRef} src={audioUrl}
                  onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                  onLoadedMetadata={event => setAudioDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
                  onDurationChange={event => setAudioDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
                  onTimeUpdate={event => setAudioCurrentTime(event.currentTarget.currentTime)}
                  onEnded={() => { setPlaying(false); setAudioCurrentTime(audioDuration) }} className="hidden" />
                <div className="grid md:grid-cols-[180px_1fr] gap-5 items-center">
                  <motion.div
                    className="vinyl-record mx-auto"
                    animate={playing ? { rotate: 360 } : { rotate: 0 }}
                    transition={{ duration: 9, ease: 'linear', repeat: playing ? Infinity : 0 }}
                    aria-label="Episode album art"
                  >
                    {coverImageUrl ? <img src={coverImageUrl} alt="Episode poster artwork" className="vinyl-art" /> : <div className="vinyl-art vinyl-art-fallback"><Film className="w-8 h-8 text-white/70" /></div>}
                    <div className="vinyl-groove groove-one" />
                    <div className="vinyl-groove groove-two" />
                    <div className="vinyl-center"><span>NOLAN</span></div>
                  </motion.div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.22em] text-nolan-accent">{seriesFormat === 'audio' ? 'Audio series · now playing' : 'Video series · audio master'}</p>
                    <h2 className="text-xl font-bold text-white mt-1">{posterTitle}</h2>
                    <p className="text-xs text-nolan-muted mt-1">Starring {posterCast[0] || 'the protagonist'} · Directed by Nolan</p>
                    <div className="flex items-center justify-center gap-0.5 h-10 my-4">
                      {Array.from({ length: 32 }).map((_, i) => (
                        <motion.div key={i} className="w-1 rounded-full bg-nolan-accent/80"
                          animate={playing ? { scaleY: [0.35, 1 + (i % 4) * 0.18, 0.35] } : { scaleY: 0.35 }}
                          transition={{ duration: 0.55 + (i % 5) * 0.08, repeat: playing ? Infinity : 0, delay: i * 0.025 }}
                          style={{ height: `${10 + (i % 5) * 4}px`, transformOrigin: 'center' }} />
                      ))}
                    </div>
                    <div className="mb-4">
                      <input
                        aria-label="Episode progress"
                        type="range"
                        min="0"
                        max={Math.max(audioDuration, 0.1)}
                        step="0.1"
                        value={Math.min(audioCurrentTime, audioDuration || 0)}
                        disabled={!audioDuration}
                        onChange={event => {
                          const nextTime = Number(event.target.value)
                          if (audioRef.current) audioRef.current.currentTime = nextTime
                          setAudioCurrentTime(nextTime)
                        }}
                        className="w-full cursor-pointer accent-nolan-accent disabled:cursor-not-allowed disabled:opacity-40"
                      />
                      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-nolan-muted">
                        <span>{formatPlaybackTime(audioCurrentTime)}</span>
                        <span>{formatPlaybackTime(audioDuration)}</span>
                      </div>
                    </div>
                    <button onClick={() => playing ? audioRef.current?.pause() : audioRef.current?.play()}
                      className="w-full py-3 bg-nolan-accent text-white rounded-xl font-bold tracking-wider text-sm flex items-center justify-center gap-3">
                      {playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                      {playing ? 'Pause episode' : 'Play episode'}
                    </button>
                  </div>
                </div>
                {audioDuration > 0 && <p className={`mt-4 text-center text-[10px] ${audioDuration >= MIN_AUDIO_SECONDS ? 'text-nolan-green' : 'text-yellow-200'}`}>{audioDuration >= MIN_AUDIO_SECONDS ? '✓ Audio master clears the 60-second minimum' : 'This take is under one minute — Nolan will extend the master before delivery.'}</p>}
                {!seriesPlan && <button onClick={doRetryAudio} disabled={busy}
                  className="mt-2 w-full py-2 text-xs text-nolan-muted hover:text-white disabled:opacity-40 flex items-center justify-center gap-2">
                  <RefreshCw className="w-3.5 h-3.5" /> Make a new audio version
                </button>}
              </div>
              </div>
              <div className="glass rounded-xl p-4 mt-3 border border-nolan-accent/30">
                <div className="flex items-center justify-between gap-2 mb-2"><div className="flex items-center gap-2"><Film className="w-4 h-4 text-nolan-accent" /><span className="text-xs font-bold tracking-wider text-white">Cinematic poster</span></div><span className="rounded-full bg-nolan-accent/10 px-2 py-1 text-[9px] text-nolan-accent">AI directed</span></div>
                <p className="text-[11px] text-nolan-muted mb-3">A compact poster built from this episode’s intent, title, cast, and atmosphere. Add one reference image if you want to steer its mood and composition.</p>
                <div className="rounded-lg border border-nolan-border/70 bg-black/15 p-3 mb-3">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-[11px] font-semibold text-white">Optional image reference</p><p className="mt-1 text-[10px] text-nolan-muted">JPG, PNG, or WEBP · under 5 MB · used only for this poster.</p></div><span className={`text-[10px] ${posterReferenceSaved ? 'text-nolan-green' : 'text-nolan-muted'}`}>{posterReferenceSaved ? 'Reference ready' : 'Optional'}</span></div>
                  <div className="mt-3 flex flex-col sm:flex-row gap-2">
                    <label className="flex-1 rounded-lg border border-dashed border-nolan-border px-3 py-2 text-[11px] text-nolan-muted cursor-pointer hover:border-nolan-accent/70"><Upload className="w-3 h-3 inline mr-1.5" />{posterReferenceFile?.name || 'Choose image'}<input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" disabled={coverGenerating || busy} onChange={event => { setPosterReferenceFile(event.target.files?.[0] || null); setPosterReferenceError('') }} /></label>
                    <button type="button" onClick={doSavePosterReference} disabled={coverGenerating || busy || !posterReferenceFile || !posterReferenceConsent} className="rounded-lg border border-nolan-accent/50 px-3 py-2 text-[11px] font-semibold text-nolan-accent disabled:opacity-40">Save reference</button>
                  </div>
                  <label className="mt-2 flex gap-2 text-[10px] text-nolan-muted"><input type="checkbox" checked={posterReferenceConsent} disabled={coverGenerating || busy} onChange={event => setPosterReferenceConsent(event.target.checked)} />I own this image or have permission to use it for this poster.</label>
                  {posterReferenceError && <p className="mt-2 text-[10px] text-red-300">{posterReferenceError}</p>}
                </div>
                <label className="block mb-3"><span className="text-[11px] font-semibold text-white">Poster direction</span><span className="block mt-1 text-[10px] text-nolan-muted">Edit the cinematic prompt. It is sent with this episode’s story and your uploaded image reference.</span><textarea value={posterPrompt} onChange={event => setPosterPrompt(event.target.value)} rows={3} placeholder={`A cinematic ${dna?.genre?.[0] || 'thriller'} backdrop: the protagonist framed against the story's central symbol, practical blue light, bold negative space.`} className="mt-2 w-full resize-none rounded-lg border border-nolan-border bg-nolan-surface/70 p-2 text-xs text-white placeholder:text-nolan-muted/50 focus:border-nolan-accent focus:outline-none" /></label>
                <button onClick={doGenerateCover} disabled={coverGenerating || busy}
                  className="w-full py-2 rounded-lg bg-nolan-accent text-white text-xs font-semibold flex items-center justify-center gap-2 disabled:opacity-40">
                  {coverGenerating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
                  {coverGenerating ? 'Creating cover…' : coverImageUrl ? 'Make a new cover' : 'Create episode cover'}
                </button>
                {coverError && <p className="text-[10px] text-red-300 mt-2">{coverError}</p>}
                {coverImageUrl && (
                  <div className="poster-frame relative aspect-[2/3] w-full max-w-[220px] overflow-hidden rounded-lg border border-nolan-accent/30 mt-3 mx-auto bg-black/20">
                    <img src={coverImageUrl} alt="Generated episode cover" className="h-full w-full object-cover" />
                    <div className="absolute inset-0 flex flex-col justify-end bg-gradient-to-t from-black/90 via-black/15 to-transparent p-4">
                      <span className="text-[9px] uppercase tracking-[0.28em] text-nolan-accent">Nolan Original</span>
                      <h3 className="mt-2 text-xl font-bold leading-tight text-white">{posterTitle}</h3>
                      <p className="mt-2 text-[9px] uppercase tracking-[0.16em] text-white/80">Starring {posterCast.slice(0, 3).join(' · ')}</p>
                      <p className="mt-1 text-[9px] uppercase tracking-[0.2em] text-nolan-accent">Directed by Nolan</p>
                    </div>
                    <span className="absolute bottom-2 left-2 rounded-full bg-black/60 px-2 py-1 text-[9px] text-white">
                      {coverIsFallback ? 'Story cover' : 'AI-generated cover'}
                    </span>
                  </div>
                )}
                <div className="mt-3 border-t border-pink-300/15 pt-3">
                  {seriesFormat === 'audio' ? (
                    <p className="text-[10px] leading-4 text-nolan-muted">Audio series keeps this as album artwork only. Your episode remains audio-first — no clips, images, or video render controls.</p>
                  ) : (
                    <>
                      <p className="text-[10px] leading-4 text-nolan-muted">Your two saved source videos are cut to the exact audio master length. The video control stays locked until both videos and the audio are ready.</p>
                      {visualPlan && <p className="text-[10px] text-pink-200 mt-2">✓ {visualPlan.beats?.length} visual moments planned for {visualPlan.target_duration_seconds}s</p>}
                      {!visualPlan && <button onClick={doPlanVisualEpisode} disabled={busy || !videoSourcesSaved} className="mt-3 w-full py-2 rounded-lg border border-pink-300/50 text-pink-200 text-xs flex justify-center gap-2 disabled:opacity-40"><Upload className="w-3 h-3" />Plan video cut</button>}
                      {visualPlan && <button onClick={doRenderVideoTeaser} disabled={busy || visualResult?.status === 'rendering'} className="mt-3 w-full py-2 rounded-lg bg-pink-300/90 text-slate-950 text-xs font-semibold flex justify-center gap-2 disabled:opacity-40">
                        {visualResult?.status === 'rendering' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Film className="w-3 h-3" />}
                        {visualResult?.status === 'rendering' ? 'Building your video…' : visualResult?.status === 'ready' ? 'Rebuild video cut' : 'Build video cut'}
                      </button>}
                      {visualError && <p className="text-[10px] text-red-300 mt-2">{visualError}</p>}
                      {visualResult?.message && <p className={`text-[10px] mt-2 ${visualResult.status === 'failed' ? 'text-red-300' : 'text-pink-200'}`}>{visualResult.message}</p>}
                      {visualResult?.url && <video controls className="mt-3 w-full rounded-lg border border-pink-300/30" src={api.absoluteUrl(visualResult.url)}>Your browser cannot play this episode video.</video>}
                    </>
                  )}
                </div>
              </div>
              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 mt-3">
                {[
                  ['Your idea', 'turned into a story'],
                  ['3 story options', 'to choose from'],
                  ['8 story checks', 'completed'],
                  ['Your choices', 'kept safe'],
                ].map(([n, l]) => (
                  <div key={n} className="glass rounded-xl p-3 text-center">
                    <p className="text-nolan-accent font-bold text-lg">{n}</p>
                    <p className="text-nolan-muted text-xs">{l}</p>
                  </div>
                ))}
              </div>
            </motion.section>
          )}

          {scriptReady && !audioUrl && !seriesPlan && (
            <div className="glass rounded-xl p-4 border border-nolan-accent/25">
              <p className="text-sm text-white font-semibold">Your episode script is ready for its audio take.</p>
              <p className="text-xs text-nolan-muted mt-1">Nolan will keep your story and recast/mix only the final audio—voices, rain, thunder, and emotional cues included.</p>
              {audioError && <p className="text-xs text-yellow-100 mt-2">{audioError}</p>}
              <button onClick={doRetryAudio} disabled={busy}
                className="mt-3 w-full py-2.5 bg-nolan-accent text-white rounded-xl text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Volume2 className="w-4 h-4" />}
                {busy ? 'Creating your audio take…' : audioError ? 'Render my episode again' : 'Create my audio episode'}
              </button>
            </div>
          )}
        </main>

        <AnimatePresence>
          {jarvisOpen && (
            <>
              <motion.button type="button" aria-label="Close director's reel" onClick={() => setJarvisOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-40 bg-[#171417]/55 backdrop-blur-sm" />
              <motion.aside initial={{ x: -420, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: -420, opacity: 0 }} transition={{ type: 'spring', stiffness: 280, damping: 28 }} className="jarvis-drawer fixed inset-y-0 left-0 z-50 flex w-full max-w-md flex-col border-r border-nolan-accent/30 bg-nolan-bg/95 shadow-2xl backdrop-blur-2xl">
                <div className="flex items-center gap-3 border-b border-nolan-border/60 px-5 py-4">
                  <span className="jarvis-core"><CircleDot className="w-5 h-5" /></span>
                  <div className="min-w-0"><p className="text-xs font-bold tracking-[0.18em] text-white">DIRECTOR&apos;S REEL</p><p className="truncate text-[10px] text-nolan-muted">{studioUpdate.role} · {studioUpdate.text}</p></div>
                  <button type="button" onClick={() => setJarvisOpen(false)} className="ml-auto rounded-full p-2 text-nolan-muted hover:bg-white/5 hover:text-white" aria-label="Close director's reel"><X className="w-4 h-4" /></button>
                </div>

                <div className="mx-5 mt-4 rounded-xl border border-nolan-accent/20 bg-nolan-accent/5 p-3">
                  <div className="flex items-center gap-2"><CircleDot className={`w-3.5 h-3.5 ${busy ? 'animate-pulse text-nolan-accent' : 'text-nolan-green'}`} /><span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-nolan-accent">{busy ? 'Live orchestration' : 'Studio ready'}</span></div>
                  <p className="mt-1 text-[11px] leading-5 text-nolan-muted">A quiet production reel: story notes, live progress, and creative decisions in one place.</p>
                </div>

          <div className="mt-4 flex min-h-0 flex-1 flex-col">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-nolan-border/50">
              <span className="text-xs text-nolan-muted tracking-widest">STORY UPDATES</span>
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

          {!seriesPlan && <div className="border-t border-nolan-border/50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Lock className="w-4 h-4 text-nolan-gold" />
              <span className="text-xs font-bold text-nolan-gold tracking-wider">KEEP WHAT YOU LOVE</span>
            </div>
            <p className="text-nolan-muted text-xs mb-2">
              Tell Nolan what to change. The details you marked to keep will stay.
            </p>
            <textarea
              value={revise}
              onChange={e => setRevise(e.target.value)}
              placeholder="Try: make it sadder, but keep Maya's final choice."
              rows={2}
              className="w-full bg-nolan-surface border border-nolan-border/70 rounded-lg p-2.5 text-xs text-nolan-text placeholder:text-nolan-muted/40 resize-none focus:outline-none focus:border-nolan-gold transition-colors"
            />
            <button onClick={() => void doRevise()} disabled={busy || !scriptReady || !revise.trim()}
              className="mt-2 w-full py-2 border border-nolan-gold/60 text-nolan-gold rounded-lg text-xs font-semibold hover:bg-nolan-gold/10 disabled:opacity-30 transition-all flex items-center justify-center gap-2">
              <RefreshCw className="w-3 h-3" /> Update my story
            </button>

            {/* Lock diff result */}
            <AnimatePresence>
              {lockDiff && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                  className="mt-3 text-xs space-y-1 border-t border-nolan-border/30 pt-3">
                  <p className="font-bold text-nolan-gold">Story updated</p>
                  {(lockDiff.affected_scene_ids || []).map((s: string) => (
                    <p key={s} className="text-nolan-red pl-2">↳ Changed: {s}</p>
                  ))}
                  {(lockDiff.preserved_elements || []).map((s: string) => (
                    <p key={s} className="text-nolan-green pl-2">✓ Kept: {s}</p>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>}
              </motion.aside>
            </>
          )}
        </AnimatePresence>
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

function StudioNote({ role, text, color }: { role: string; text: string; color: 'purple' | 'blue' | 'gold' }) {
  const colors = { purple: 'border-purple-400/30 bg-purple-400/5 text-purple-200', blue: 'border-blue-400/30 bg-blue-400/5 text-blue-200', gold: 'border-yellow-400/30 bg-yellow-400/5 text-yellow-100' }
  return <div className={`rounded-xl border p-3 ${colors[color]}`}><p className="text-[10px] font-bold uppercase tracking-[0.16em] opacity-70">{role}</p><p className="text-xs mt-1">{text}</p></div>
}

function DNARow({ label, value, field, locked, onToggle, highlight }:
  { label: string; value: string; field: string; locked: Set<string>; onToggle: (f: string) => void; highlight?: boolean }) {
  const isLocked = locked.has(field)
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-nolan-border/20 group">
      <button onClick={() => onToggle(field)} className="mt-0.5 flex-shrink-0" title={isLocked ? 'Allow changes to this detail' : 'Keep this detail'}>
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

function EpisodeStatusPill({ status }: { status: EpisodeStatus }) {
  const labels: Record<EpisodeStatus, string> = {
    OUTLINED: 'Waiting',
    DRAFTING: 'Writing',
    DRAFT_READY: 'Ready to make',
    RENDERING: 'Making audio',
    READY: 'Ready to review',
    APPROVED: 'Approved',
    REVISING: 'Updating',
    STALE: 'Needs refresh',
  }
  const colors: Record<EpisodeStatus, string> = {
    OUTLINED: 'bg-nolan-surface text-nolan-muted',
    DRAFTING: 'bg-yellow-400/10 text-yellow-200',
    DRAFT_READY: 'bg-nolan-accent/15 text-nolan-accent',
    RENDERING: 'bg-yellow-400/10 text-yellow-200',
    READY: 'bg-pink-300/10 text-pink-200',
    APPROVED: 'bg-nolan-green/10 text-nolan-green',
    REVISING: 'bg-yellow-400/10 text-yellow-200',
    STALE: 'bg-nolan-red/10 text-red-200',
  }
  return <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-medium ${colors[status]}`}>{labels[status]}</span>
}

function ScreenplayPaper({ script, editing, busy, error, onEdit, onCancel, onChange, onSave, onGenerate, canGenerate = false, compact = false }: {
  script: ProductionScript; editing: boolean; busy: boolean; error: string; compact?: boolean; canGenerate?: boolean
  onEdit: () => void; onCancel: () => void; onChange: (script: ProductionScript) => void; onSave: () => void; onGenerate: () => void
}) {
  const updateLine = (index: number, field: keyof ScriptLine, value: string) => onChange({ ...script, lines: script.lines.map((line, i) => i === index ? { ...line, [field]: field === 'duration_seconds' ? Number(value) || 0 : value } : line) })
  return <div className={`screenplay-paper ${compact ? 'xl:mt-2' : 'mt-2'} rounded-xl p-5`}>
    <div className="mb-4 flex items-start justify-between gap-3 border-b border-amber-950/20 pb-3"><div><p className="screenplay-kicker">NOLAN · SHOOTING DRAFT</p><h3 className="mt-1 font-serif text-lg font-bold text-stone-900">{script.title}</h3><p className="mt-1 text-[10px] text-stone-600">Dialogue · pauses · SFX — the exact audio blueprint.</p></div>{!editing ? <button onClick={onEdit} disabled={busy} className="rounded border border-stone-700 px-2 py-1 text-[10px] font-semibold text-stone-800 disabled:opacity-40">Edit script</button> : <div className="flex gap-2"><button onClick={onCancel} disabled={busy} className="text-[10px] text-stone-600">Cancel</button><button onClick={onSave} disabled={busy} className="rounded bg-stone-900 px-2 py-1 text-[10px] font-semibold text-amber-50 disabled:opacity-40">{busy ? 'Saving…' : 'Save'}</button></div>}</div>
    <div className="max-h-[460px] space-y-3 overflow-y-auto pr-1">{script.lines.map((line, index) => {
      const cue = line.type === 'dialogue' ? line.text || '' : line.description || line.text || ''
      if (editing) return <div key={index} className="rounded border border-amber-950/20 bg-amber-50/60 p-2"><div className="flex gap-2"><select value={line.type} onChange={e => updateLine(index, 'type', e.target.value)} className="w-24 bg-transparent text-[10px] text-stone-700"><option value="dialogue">Dialogue</option><option value="sfx">SFX</option><option value="ambience">Ambience</option><option value="music">Music</option><option value="silence">Silence</option></select>{line.type === 'dialogue' && <input value={line.character || ''} onChange={e => updateLine(index, 'character', e.target.value)} placeholder="Character" className="min-w-0 flex-1 bg-transparent text-[10px] font-bold uppercase text-stone-800 outline-none" />}</div><textarea value={cue} onChange={e => updateLine(index, line.type === 'dialogue' ? 'text' : 'description', e.target.value)} rows={2} className="mt-1 w-full resize-none bg-transparent text-xs leading-5 text-stone-800 outline-none" />{line.type === 'silence' && <input type="number" value={line.duration_seconds || 0} onChange={e => updateLine(index, 'duration_seconds', e.target.value)} className="w-16 bg-transparent text-[10px] text-stone-700 outline-none" />}</div>
      if (line.type === 'dialogue') return <div key={index} className="pl-8"><p className="text-[10px] font-bold uppercase tracking-[0.13em] text-stone-800">{line.character || 'NARRATOR'} {line.emotion ? `(${line.emotion})` : ''}</p><p className="mt-1 font-serif text-sm leading-6 text-stone-900">{cue}</p></div>
      return <p key={index} className="text-[10px] font-semibold uppercase tracking-[0.08em] text-stone-600">[{line.type}{cue ? ` — ${cue}` : ''}{line.duration_seconds ? ` · ${line.duration_seconds}s` : ''}]</p>
    })}</div>{error && <p className="mt-3 text-[10px] text-red-700">{error}</p>}{!editing && canGenerate && <button onClick={onGenerate} disabled={busy} className="screenplay-generate mt-4 w-full rounded-lg py-2.5 text-[10px] font-bold uppercase tracking-[.14em] text-white disabled:opacity-40"><Volume2 className="mr-1.5 inline h-3.5 w-3.5" />Generate revised audio</button>}</div>
}

function VisionCard({ vision, selected, onSelect }:
  { vision: Vision; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const fitLabel = vision.constitution_score >= 85 ? 'Strong story fit' :
                   vision.constitution_score >= 70 ? 'Good story fit' : 'Needs a little shaping'
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
            <span className="shrink-0 rounded-full bg-nolan-accent/10 px-2 py-1 text-[10px] font-medium text-nolan-accent">{fitLabel}</span>
          </div>
          <p className="text-nolan-muted text-xs leading-5 mt-1">{vision.premise}</p>
          <p className="text-blue-200/80 text-[11px] leading-4 mt-2">It moves from {vision.emotional_trajectory}.</p>
          <p className="text-nolan-muted text-[11px] leading-4 mt-1">Why it fits: {vision.why_it_fits_dna}</p>
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

function ConstitutionPendingRow({ rule }: { rule: { rule_number: number; rule: string } }) {
  return (
    <div className="rounded-lg px-3 py-2 bg-black/10 border border-nolan-border/40">
      <div className="flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 text-nolan-muted animate-spin flex-shrink-0" />
        <span className="text-xs text-nolan-text/70 flex-1">Story check {rule.rule_number}: {rule.rule}</span>
        <span className="text-[10px] text-nolan-muted">Waiting for supervisor</span>
      </div>
    </div>
  )
}

function ConstitutionRow({ check, onRepair, disabled }: { check: Check; onRepair?: (check: Check) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(!check.passed)
  return (
    <div className={`rounded-lg px-3 py-2 transition-all ${check.passed ? 'bg-nolan-green/5' : 'bg-nolan-red/8 border border-nolan-red/20'}`}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen(!open)}>
        {check.passed
          ? <CheckCircle className="w-3.5 h-3.5 text-nolan-green flex-shrink-0" />
          : <XCircle className="w-3.5 h-3.5 text-nolan-red flex-shrink-0" />}
        <span className="text-xs text-nolan-text flex-1">Story check {check.rule_number}: {check.rule}</span>
        {!check.passed && <ChevronDown className={`w-3 h-3 text-nolan-muted transition-transform ${open ? '' : '-rotate-90'}`} />}
      </div>
      <AnimatePresence>
        {open && !check.passed && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}>
            {check.evidence && <p className="text-[11px] text-nolan-muted mt-1 pl-5">What Nolan found: {check.evidence.slice(0, 120)}</p>}
            {check.repair  && <p className="text-[11px] text-nolan-green mt-1 pl-5">↳ Try this: {check.repair.slice(0, 120)}</p>}
            {check.repair && onRepair && <button type="button" onClick={event => { event.stopPropagation(); void onRepair(check) }} disabled={disabled}
              className="mt-2 ml-5 rounded-md border border-nolan-green/40 px-2.5 py-1 text-[10px] font-semibold text-nolan-green hover:bg-nolan-green/10 disabled:opacity-40"><Wand2 className="w-3 h-3 inline mr-1" />Apply repair</button>}
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
