const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const api = {
  async createSession() {
    const r = await fetch(`${API}/api/sessions`, { method: 'POST' })
    return r.json()
  },
  async submitAudio(sessionId: string, fd: FormData) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/idea-audio`, { method: 'POST', body: fd })
    return r.json()
  },
  async extractDNA(sessionId: string, transcript: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/extract-dna`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript }),
    })
    return r.json()
  },
  async updateDNA(sessionId: string, dna: any) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/creative-dna`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative_dna: dna }),
    })
    return r.json()
  },
  async generateVisions(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/generate-visions`, { method: 'POST' })
    return r.json()
  },
  async produce(sessionId: string, visionSelection: any) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/produce`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vision_selection: visionSelection }),
    })
    return r.json()
  },
  async revise(sessionId: string, changeInstruction: string, preserveElements: string[]) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_request: { change_instruction: changeInstruction, preserve_elements: preserveElements } }),
    })
    return r.json()
  },
  async getSession(sessionId: string) {
    const r = await fetch(`${API}/api/sessions/${sessionId}`)
    return r.json()
  },
  async cloneVoice(sessionId: string, fd: FormData) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/voice-cameo/clone`, { method: 'POST', body: fd })
    return r.json()
  },
  async deleteCameo(sessionId: string) {
    await fetch(`${API}/api/sessions/${sessionId}/voice-cameo`, { method: 'DELETE' })
  },
  async uploadVisualAsset(sessionId: string, assetName: 'portrait' | 'live_video', file: File) {
    const fd = new FormData()
    fd.append('asset', file)
    fd.append('consent', 'true')
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-assets/${assetName}`, { method: 'POST', body: fd })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },
  async planVisualEpisode(sessionId: string, portraitConsent: boolean, liveVideoConsent: boolean) {
    const r = await fetch(`${API}/api/sessions/${sessionId}/visual-episode/plan?portrait_consent=${portraitConsent}&live_video_consent=${liveVideoConsent}`, { method: 'POST' })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },
  audioUrl(sessionId: string, file = 'pilot.mp3') {
    return `${API}/audio/${sessionId}/${file}`
  },
  eventsUrl(sessionId: string) {
    return `${API}/api/sessions/${sessionId}/events`
  },
}
