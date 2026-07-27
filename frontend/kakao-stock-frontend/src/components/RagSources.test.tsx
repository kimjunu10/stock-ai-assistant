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

    expect(screen.getByRole('link', { name: /반도체 전망 PDF 다운로드/ }).getAttribute('href'))
      .toBe('/api/stocks/005930/reports/report-1/download')
    expect(screen.getByText('PDF')).toBeTruthy()
  })

  it('keeps report viewing and PDF download as separate actions', () => {
    render(<RagSources sources={[{
      sourceId: 'report-source',
      sourceType: 'research_report',
      title: '원문이 있는 리포트',
      url: 'https://example.com/report',
      locator: { report_id: 'report-2' },
    }]} stockCode="005930" />)

    expect(screen.getByRole('link', { name: /원문 보기/ }).getAttribute('href'))
      .toBe('https://example.com/report')
    expect(screen.getByRole('link', { name: '원문이 있는 리포트 PDF 다운로드' }).getAttribute('href'))
      .toBe('/api/stocks/005930/reports/report-2/download')
    expect(screen.getByRole('button', { name: '원문이 있는 리포트 원문 미리보기' }))
      .toBeTruthy()
  })
})
