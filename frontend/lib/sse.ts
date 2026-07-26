'use client'
import { useEffect, useRef, useCallback } from 'react'

export type SSEEvent = {
  agent: string
  type: 'token' | 'artifact' | 'violation' | 'repair' | 'complete' | 'fallback' | 'error' | 'status' | 'ping' | 'close'
  data: any
}

export function useSSE(url: string | null, onEvent: (e: SSEEvent) => void) {
  const esRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!url) return
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const parsed: SSEEvent = JSON.parse(e.data)
        if (parsed.type === 'close') { es.close(); return }
        if (parsed.type === 'ping') return
        onEventRef.current(parsed)
      } catch {}
    }

    es.onerror = () => {
      es.close()
    }

    return () => { es.close() }
  }, [url])
}
