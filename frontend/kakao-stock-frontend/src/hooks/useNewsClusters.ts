import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchNewsClusters } from '../api/news'
import type { NewsCluster, StockIssueBrief } from '../types'

export function useNewsClusters(options: { limit?: number; publishedDate?: string; stockCode?: string } = {}) {
  const [clusters, setClusters] = useState<NewsCluster[]>([])
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [issueBrief, setIssueBrief] = useState<StockIssueBrief | null>(null)
  const [total, setTotal] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const requestKeyRef = useRef('')
  const loadMoreControllerRef = useRef<AbortController | null>(null)
  const limit = options.limit ?? 20
  const publishedDate = options.publishedDate
  const stockCode = options.stockCode

  useEffect(() => {
    const controller = new AbortController()
    const requestKey = `${stockCode ?? 'all'}:${publishedDate ?? 'all'}:${limit}:${attempt}`
    requestKeyRef.current = requestKey
    loadMoreControllerRef.current?.abort()
    setIsLoading(true)
    setIsLoadingMore(false)
    setError('')
    fetchNewsClusters(controller.signal, { limit, offset: 0, publishedDate, stockCode })
      .then((response) => {
        if (requestKeyRef.current !== requestKey) return
        setClusters(response.clusters)
        setIssueBrief(response.issueBrief)
        setTotal(response.total)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setClusters([])
          setIssueBrief(null)
          setError(reason instanceof Error ? reason.message : '뉴스 브리핑을 불러오지 못했어요.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [attempt, limit, publishedDate, stockCode])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  const loadMore = useCallback(() => {
    if (isLoading || isLoadingMore || clusters.length >= total) return
    const controller = new AbortController()
    loadMoreControllerRef.current?.abort()
    loadMoreControllerRef.current = controller
    const requestKey = requestKeyRef.current
    setIsLoadingMore(true)
    fetchNewsClusters(controller.signal, { limit, offset: clusters.length, publishedDate, stockCode })
      .then((response) => {
        if (requestKeyRef.current !== requestKey) return
        setClusters((current) => {
          const known = new Set(current.map((cluster) => cluster.id))
          return [...current, ...response.clusters.filter((cluster) => !known.has(cluster.id))]
        })
        setTotal(response.total)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '뉴스를 더 불러오지 못했어요.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && requestKeyRef.current === requestKey) {
          setIsLoadingMore(false)
        }
      })
  }, [clusters, isLoading, isLoadingMore, limit, publishedDate, stockCode, total])

  return {
    clusters,
    error,
    hasMore: clusters.length < total,
    isLoading,
    isLoadingMore,
    issueBrief,
    loadMore,
    retry,
    total,
  }
}
