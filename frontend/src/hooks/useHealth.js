import { useEffect, useState } from 'react'
import { fetchHealth } from '../api/client'

/** Polls the API health endpoint so the header can show live system status. */
export function useHealth(intervalMs = 60000) {
  const [health, setHealth] = useState({ status: 'checking', data: null })

  useEffect(() => {
    let alive = true
    const check = () =>
      fetchHealth()
        .then((data) => alive && setHealth({ status: data.status, data }))
        .catch(() => alive && setHealth({ status: 'offline', data: null }))
    check()
    const id = setInterval(check, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [intervalMs])

  return health
}
