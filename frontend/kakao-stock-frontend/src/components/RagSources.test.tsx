import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RagSources } from './RagSources'

describe('RagSources', () => {
  it('offers a private report through the backend download route', () => {
    render(<RagSources sources={[{
      sourceId: 'chunk-1',
      sourceType: 'research_report',
      title: '반도체 전망',
      publisher: '테스트증권',
      locator: { report_id: 'report-1' },
    }]} stockCode="005930" />)

    expect(screen.getByRole('link', { name: /반도체 전망/ }).getAttribute('href'))
      .toBe('/api/stocks/005930/reports/report-1/download')
    expect(screen.getByText('PDF')).toBeTruthy()
  })
})
