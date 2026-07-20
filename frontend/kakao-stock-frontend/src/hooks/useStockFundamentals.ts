import { useEffect, useState } from 'react'
import { fetchDisclosures, fetchFinancialSummary } from '../api/fundamentals'
import type { DisclosureItem, FinancialItem } from '../types'

export function useStockFundamentals(stockCode: string) {
  const [financials, setFinancials] = useState<FinancialItem[]>([])
  const [disclosures, setDisclosures] = useState<DisclosureItem[]>([])
  const [financialError, setFinancialError] = useState('')
  const [disclosureError, setDisclosureError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setFinancials([])
    setDisclosures([])
    setFinancialError('')
    setDisclosureError('')

    fetchFinancialSummary(stockCode, controller.signal)
      .then((response) => setFinancials(response.items))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setFinancialError(reason instanceof Error ? reason.message : 'DART 재무 데이터를 불러오지 못했어요.')
        }
      })

    fetchDisclosures(stockCode, controller.signal)
      .then((response) => setDisclosures(response.items))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setDisclosureError(reason instanceof Error ? reason.message : 'DART 공시를 불러오지 못했어요.')
        }
      })

    return () => controller.abort()
  }, [stockCode])

  return { disclosureError, disclosures, financialError, financials }
}
