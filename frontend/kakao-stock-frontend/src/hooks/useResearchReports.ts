import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchResearchReports } from '../api/reports'
import type { ReportItem } from '../types'

export function useResearchReports(stockCode: string) {
  const [items, setItems] = useState<ReportItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const requestKeyRef = useRef(stockCode)
  const loadMoreControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    requestKeyRef.current = stockCode
    loadMoreControllerRef.current?.abort()
    setItems([])
    setTotal(0)
    setIsLoading(true)
    setIsLoadingMore(false)
    setError('')
    fetchResearchReports(stockCode, controller.signal)
      .then((response) => {
        setItems(response.items)
        setTotal(response.total)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '증권사 리포트를 불러오지 못했어요.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => {
      controller.abort()
      loadMoreControllerRef.current?.abort()
    }
  }, [stockCode])

  const loadMore = useCallback(() => {
    if (isLoading || isLoadingMore || items.length >= total) return
    const controller = new AbortController()
    loadMoreControllerRef.current?.abort()
    loadMoreControllerRef.current = controller
    const requestKey = requestKeyRef.current
    setIsLoadingMore(true)
    fetchResearchReports(stockCode, controller.signal, 8, items.length)
      .then((response) => {
        if (requestKeyRef.current !== requestKey) return
        setItems((current) => {
          const known = new Set(current.map((item) => item.id))
          return [...current, ...response.items.filter((item) => !known.has(item.id))]
        })
        setTotal(response.total)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '리포트를 더 불러오지 못했어요.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && requestKeyRef.current === requestKey) {
          setIsLoadingMore(false)
        }
      })
  }, [isLoading, isLoadingMore, items, stockCode, total])

  return {
    error,
    hasMore: items.length < total,
    isLoading,
    isLoadingMore,
    items,
    loadMore,
    total,
  }
}
