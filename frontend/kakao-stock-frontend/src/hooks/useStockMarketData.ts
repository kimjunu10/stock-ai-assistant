import { useCallback, useEffect, useState } from 'react'
import { fetchStockMarketData } from '../api/marketData'
import type { MarketDataStatus, StockMarketData } from '../types'

export function useStockMarketData(stockCode: string) {
  const [data, setData] = useState<StockMarketData | null>(null)
  const [status, setStatus] = useState<MarketDataStatus>('loading')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setStatus('loading')
    setError('')

    fetchStockMarketData(stockCode, controller.signal)
      .then((marketData) => {
        setData(marketData)
        setStatus('ready')
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : '실제 시세를 불러오지 못했어요.')
        setStatus('error')
      })

    return () => controller.abort()
  }, [attempt, stockCode])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])

  return { data, error, retry, status }
}
