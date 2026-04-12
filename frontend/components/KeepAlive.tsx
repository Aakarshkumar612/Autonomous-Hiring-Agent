'use client'

/**
 * KeepAlive — silent background component that pings the FastAPI backend
 * every 10 minutes to prevent the server from sleeping on free hosting tiers
 * (Render, Railway, Fly.io, etc.).
 *
 * Behaviour:
 *  - Pings immediately on mount (critical: wakes a cold-start server the moment
 *    the user opens the dashboard, before they attempt any real API call)
 *  - Then pings every INTERVAL_MS (10 minutes)
 *  - Pauses the interval when the browser tab is hidden
 *  - Resumes + pings immediately when the tab becomes visible again,
 *    if more than RESUME_THRESHOLD_MS has passed since the last ping
 *  - Retries up to MAX_RETRIES times with exponential back-off on failure
 *  - Completely silent — never shows errors to the user
 *  - Cleans up interval and event listeners on unmount
 */

import { useEffect, useRef } from 'react'

const INTERVAL_MS       = 10 * 60 * 1000  // 10 minutes
const RESUME_THRESHOLD  =  5 * 60 * 1000  // re-ping on tab focus if >5 min since last
const MAX_RETRIES       = 3
const RETRY_BASE_MS     = 5_000           // 5s, 10s, 20s

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function pingBackend(attempt = 1): Promise<void> {
  try {
    const res = await fetch(`${API_URL}/health`, {
      method:  'GET',
      headers: { 'Accept': 'application/json' },
      // Short timeout — this is a keepalive ping, not a data request
      signal: AbortSignal.timeout(8_000),
    })

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`)
    }

    // Success — log only in development so it is visible during local testing
    if (process.env.NODE_ENV === 'development') {
      const { status, timestamp } = await res.json().catch(() => ({}))
      console.debug(`[KeepAlive] ✓ backend ${status ?? 'ok'} — ${timestamp ?? new Date().toISOString()}`)
    }
  } catch (err) {
    if (attempt < MAX_RETRIES) {
      const delay = RETRY_BASE_MS * Math.pow(2, attempt - 1)  // 5s, 10s, 20s
      if (process.env.NODE_ENV === 'development') {
        console.debug(`[KeepAlive] retry ${attempt}/${MAX_RETRIES} in ${delay / 1000}s`)
      }
      await new Promise((r) => setTimeout(r, delay))
      return pingBackend(attempt + 1)
    }
    // All retries exhausted — silently give up until next scheduled interval
    if (process.env.NODE_ENV === 'development') {
      console.debug('[KeepAlive] backend unreachable after max retries — will retry at next interval')
    }
  }
}

export default function KeepAlive() {
  const intervalRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastPingRef     = useRef<number>(0)
  const isVisibleRef    = useRef<boolean>(true)

  function startInterval() {
    stopInterval()
    intervalRef.current = setInterval(() => {
      if (isVisibleRef.current) {
        lastPingRef.current = Date.now()
        pingBackend()
      }
    }, INTERVAL_MS)
  }

  function stopInterval() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  function handleVisibilityChange() {
    if (document.visibilityState === 'hidden') {
      // Tab went to background — pause interval to avoid unnecessary pings
      isVisibleRef.current = false
      stopInterval()
    } else {
      // Tab came back to foreground
      isVisibleRef.current = true
      const timeSinceLastPing = Date.now() - lastPingRef.current

      // If the backend may have gone to sleep while the tab was hidden, ping now
      if (timeSinceLastPing > RESUME_THRESHOLD) {
        lastPingRef.current = Date.now()
        pingBackend()
      }

      // Restart the regular interval
      startInterval()
    }
  }

  useEffect(() => {
    // Ping immediately on mount — wakes a cold server before the user touches anything
    lastPingRef.current = Date.now()
    pingBackend()

    // Start the regular 10-minute interval
    startInterval()

    // Pause / resume based on tab visibility
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopInterval()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Renders nothing — purely a background behaviour component
  return null
}
