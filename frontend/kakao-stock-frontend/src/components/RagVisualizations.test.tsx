import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RagVisualizations } from './RagVisualizations'

describe('RagVisualizations', () => {
  it('labels actual financial values and broker forecasts separately', () => {
    render(<RagVisualizations visualizations={[
      {
        type: 'financial_series',
        title: 'DART 공식 재무정보',
        data: { items: [{ label: '영업이익', value_display: '43.60조', period: '2025 연간', basis: '연결', value_kind: 'actual' }] },
        sourceIds: ['f1'],
      },
      {
        type: 'broker_targets',
        title: '증권사 목표주가',
        data: { items: [{ broker: '테스트증권', report_date: '2026-07-01', target_price: 300000, target_price_currency: 'KRW', investment_opinion: '매수' }] },
        sourceIds: ['r1'],
      },
    ]} />)
    expect(screen.getByText('공식 실제값')).toBeTruthy()
    expect(screen.getByText('증권사 전망')).toBeTruthy()
    expect(screen.getByText('목표주가는 증권사의 전망이며 실제 시장 가격이나 확정값이 아닙니다.')).toBeTruthy()
  })
})
