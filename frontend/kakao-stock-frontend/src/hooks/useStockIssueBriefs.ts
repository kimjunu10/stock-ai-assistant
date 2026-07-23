import { useEffect, useState } from 'react'
import { fetchNewsClusters } from '../api/news'
import { STOCKS } from '../data/mockData'
import type { StockIssueBrief } from '../types'

export function useStockIssueBriefs() {
  const [briefs, setBriefs] = useState<Record<string, StockIssueBrief | null>>({})
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    Promise.all(
      STOCKS.map(async (stock) => {
        const response = await fetchNewsClusters(controller.signal, { limit: 1, stockCode: stock.code })
        return [stock.code, response.issueBrief] as const
      }),
    )
      .then((entries) => {
        if (!controller.signal.aborted) setBriefs(Object.fromEntries(entries))
      })
      .catch(() => {
        if (!controller.signal.aborted) setBriefs({})
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [])

  return { briefs, isLoading }
}
