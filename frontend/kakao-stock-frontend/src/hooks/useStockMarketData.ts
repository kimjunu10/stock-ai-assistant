import { useCallback, useEffect, useState } from 'react'
import { fetchStockMarketData } from '../api/marketData'
import type { MarketDataStatus, StockMarketData } from '../types'

export function useStockMarketData(stockCode: string) {
  const [data, setData] = useState<StockMarketData | null>(null)
  const [status, setStatus] = useState<MarketDataStatus>('loading')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false
    setData(null)
    setStatus('loading')
    setError('')

    const refresh = () => {
      if (document.visibilityState === 'hidden' || inFlight) return
      inFlight = true
      setIsRefreshing(true)
      fetchStockMarketData(stockCode, controller.signal)
        .then((marketData) => {
          setData(marketData)
          setStatus('ready')
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return
          setError(reason instanceof Error ? reason.message : '실제 시세를 불러오지 못했어요.')
          setStatus((current) => current === 'ready' ? current : 'error')
        })
        .finally(() => {
          inFlight = false
          if (!controller.signal.aborted) setIsRefreshing(false)
        })
    }

    refresh()
    const intervalId = window.setInterval(refresh, 15_000)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      controller.abort()
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [attempt, stockCode])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])

  return { data, error, isRefreshing, retry, status }
}
