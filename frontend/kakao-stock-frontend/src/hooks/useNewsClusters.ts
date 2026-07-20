import { useCallback, useEffect, useState } from 'react'
import { fetchNewsClusters } from '../api/news'
import type { NewsCluster } from '../types'

export function useNewsClusters(options: { limit?: number; stockCode?: string } = {}) {
  const [clusters, setClusters] = useState<NewsCluster[]>([])
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const limit = options.limit ?? 20
  const stockCode = options.stockCode

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    setError('')
    fetchNewsClusters(controller.signal, { limit, stockCode })
      .then(setClusters)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setClusters([])
          setError(reason instanceof Error ? reason.message : '뉴스 브리핑을 불러오지 못했어요.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [attempt, limit, stockCode])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  return { clusters, error, isLoading, retry }
}
