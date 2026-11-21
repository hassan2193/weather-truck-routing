import { useCallback, useRef, useState } from 'react'
import { analyzeTrip } from '../api/client'

/** Runs a trip analysis; a newer request cancels any request still in flight. */
export function useAnalysis() {
  const [state, setState] = useState({ status: 'idle', data: null, error: null })
  const controller = useRef(null)

  const run = useCallback(async (payload) => {
    controller.current?.abort()
    const ctrl = new AbortController()
    controller.current = ctrl
    setState((s) => ({ status: 'loading', data: s.data, error: null }))
    try {
      const data = await analyzeTrip(payload, ctrl.signal)
      if (ctrl.signal.aborted) return null
      setState({ status: 'success', data, error: null })
      return data
    } catch (error) {
      if (ctrl.signal.aborted) return null
      setState((s) => ({ status: 'error', data: s.data, error }))
      return null
    }
  }, [])

  return { ...state, run }
}
