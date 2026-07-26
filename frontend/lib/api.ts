const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type VoiceCameoConsent = {
  confirmed: boolean
  assigned_to: 'narrator' | 'character'
  character_name: string | null
}

async function jsonOrThrow(response: Response) {
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed (${response.status})`)
  }
  return response.json()
}

export const api = {
  async createSession() {
    const r = await fetch(`${API}/api/sessions`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async submitAudio(sessionId: string, fd: FormData) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/idea-audio`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async extractDNA(sessionId: string, transcript: string, outputLanguage = 'auto') {
    const r = await fetch(`${API}/api/sessions/${sessionId}/extract-dna`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, output_language: outputLanguage }),
    })
    return jsonOrThrow(r)
  },
  async updatePreferences(
    sessionId: string,
    outputLanguage: string,
    voiceCast: Record<string, string> = {},
    outputMode: 'audio' | 'video' = 'audio',
  ) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/preferences`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ output_language: outputLanguage, output_mode: outputMode, voice_cast: voiceCast }),
    })
    return jsonOrThrow(r)
  },
  async getVoices() {
    const r = await fetch(`${API}/api/voices`)
    return jsonOrThrow(r)
  },
  async updateDNA(sessionId: string, dna: any) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/creative-dna`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative_dna: dna }),
    })
    return jsonOrThrow(r)
  },
  async generateVisions(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/generate-visions`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async produce(sessionId: string, visionSelection: any) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/produce`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vision_selection: visionSelection }),
    })
    return jsonOrThrow(r)
  },
  async createSeries(sessionId: string, visionSelection: any) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/series`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vision_selection: visionSelection }),
    })
    return jsonOrThrow(r)
  },
  async draftEpisode(sessionId: string, episodeNumber: number) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/episodes/${episodeNumber}/draft`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async confirmEpisode(sessionId: string, episodeNumber: number) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/episodes/${episodeNumber}/confirm`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async submitEpisodeFeedback(
    sessionId: string,
    episodeNumber: number,
    action: 'revise' | 'continue',
    feedback: { keep: string; change_this_episode: string; next_direction: string },
  ) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/episodes/${episodeNumber}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, feedback }),
    })
    return jsonOrThrow(r)
  },
  async applyConstitutionRepair(sessionId: string, episodeNumber: number, ruleNumber: number, repair: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/episodes/${episodeNumber}/constitution-repair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule_number: ruleNumber, repair }),
    })
    return jsonOrThrow(r)
  },
  async renderAudio(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/render-audio`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async revise(sessionId: string, changeInstruction: string, preserveElements: string[]) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_request: { change_instruction: changeInstruction, preserve_elements: preserveElements } }),
    })
    return jsonOrThrow(r)
  },
  async getSession(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}`)
    return jsonOrThrow(r)
  },
  async recordVoiceConsent(sessionId: string, consent: VoiceCameoConsent) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/voice-cameo/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(consent),
    })
    return jsonOrThrow(r)
  },
  async cloneVoice(sessionId: string, fd: FormData) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/voice-cameo/clone`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async deleteCameo(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/voice-cameo`, { method: 'DELETE' })
    return jsonOrThrow(r)
  },
  async generateCoverImage(sessionId: string, episodeNumber?: number, posterPrompt = '') {
    const suffix = episodeNumber ? `?episode_number=${episodeNumber}` : ''
    const r = await fetch(`${API}/api/sessions/${sessionId}/cover-image${suffix}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ poster_prompt: posterPrompt }),
    })
    return jsonOrThrow(r)
  },
  async updateEpisodeScript(sessionId: string, episodeNumber: number, productionScript: unknown) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/episodes/${episodeNumber}/script`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ production_script: productionScript }),
    })
    return jsonOrThrow(r)
  },
  async uploadPosterReference(sessionId: string, file: File, consent: boolean) {
    const fd = new FormData()
    fd.append('asset', file)
    fd.append('consent', String(consent))
    const r = await fetch(`${API}/api/sessions/${sessionId}/poster-reference`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async uploadSeriesVideo(sessionId: string, slot: 'video_1' | 'video_2', file: File, consent: boolean) {
    const fd = new FormData()
    fd.append('asset', file)
    fd.append('consent', String(consent))
    const r = await fetch(`${API}/api/sessions/${sessionId}/series-videos/${slot}`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async uploadVisualAsset(sessionId: string, assetName: 'portrait' | 'live_video', file: File, consent: boolean) {
    const fd = new FormData()
    fd.append('asset', file)
    fd.append('consent', String(consent))
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-assets/${assetName}`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async uploadStoryAsset(sessionId: string, kind: 'photo' | 'video' | 'place_reference', file: File, consent: boolean) {
    const fd = new FormData()
    fd.append('asset', file)
    fd.append('kind', kind)
    fd.append('consent', String(consent))
    const r = await fetch(`${API}/api/sessions/${sessionId}/story-assets`, { method: 'POST', body: fd })
    return jsonOrThrow(r)
  },
  async planVisualEpisode(sessionId: string, portraitConsent: boolean, liveVideoConsent: boolean, episodeNumber?: number) {
    const episodeQuery = episodeNumber ? `&episode_number=${episodeNumber}` : ''
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-episode/plan?portrait_consent=${portraitConsent}&live_video_consent=${liveVideoConsent}${episodeQuery}`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async renderVideoTeaser(sessionId: string, episodeNumber?: number) {
    const suffix = episodeNumber ? `?episode_number=${episodeNumber}` : ''
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-episode/render${suffix}`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  async composeEpisodeVideo(sessionId: string, episodeNumber?: number) {
    const suffix = episodeNumber ? `?episode_number=${episodeNumber}` : ''
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-episode/compose${suffix}`, { method: 'POST' })
    return jsonOrThrow(r)
  },
  audioUrl(sessionId: string, file = 'pilot.mp3') {
    return `${API}/audio/${sessionId}/${file}`
  },
  absoluteUrl(path: string) {
    return path.startsWith('http://') || path.startsWith('https://') ? path : `${API}${path}`
  },
  eventsUrl(sessionId: string) {
    return `${API}/api/sessions/${sessionId}/events`
  },
}
