import { useEffect, useState } from 'react'
import { fetchStockMarketOverview } from '../api/marketData'
import type { StockListQuote } from '../types'

export function useStockMarketOverview() {
  const [quotes, setQuotes] = useState<Record<string, StockListQuote>>({})
  const [isRefreshing, setIsRefreshing] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false

    const refresh = () => {
      if (document.visibilityState === 'hidden' || inFlight) return
      inFlight = true
      setIsRefreshing(true)
      fetchStockMarketOverview(controller.signal)
        .then((overview) => {
          setQuotes(Object.fromEntries(overview.quotes.map((quote) => [quote.stockCode, quote])))
          setError('')
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(reason instanceof Error ? reason.message : '실제 시세를 불러오지 못했어요.')
          }
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
  }, [])

  return { error, isRefreshing, quotes }
}
