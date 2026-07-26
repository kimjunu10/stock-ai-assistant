import { useEffect, useState } from 'react'
import { fetchCompanyProfile, fetchFinancialSummary } from '../api/fundamentals'
import type { FinancialItem, StockCompanyProfile } from '../types'

export function useStockFundamentals(stockCode: string) {
  const [financials, setFinancials] = useState<FinancialItem[]>([])
  const [financialError, setFinancialError] = useState('')
  const [companyProfile, setCompanyProfile] = useState<StockCompanyProfile | null>(null)
  const [companyProfileError, setCompanyProfileError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setFinancials([])
    setFinancialError('')
    setCompanyProfile(null)
    setCompanyProfileError('')

    fetchCompanyProfile(stockCode, controller.signal)
      .then(setCompanyProfile)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setCompanyProfileError(reason instanceof Error ? reason.message : '회사 기본 정보를 불러오지 못했어요.')
        }
      })

    fetchFinancialSummary(stockCode, controller.signal)
      .then((response) => setFinancials(response.items))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setFinancialError(reason instanceof Error ? reason.message : 'DART 재무 데이터를 불러오지 못했어요.')
        }
      })

    return () => controller.abort()
  }, [stockCode])

  return {
    companyProfile,
    companyProfileError,
    financialError,
    financials,
  }
}
