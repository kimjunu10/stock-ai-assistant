import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RagVisualizations } from './RagVisualizations'

describe('RagVisualizations', () => {
  it('renders verified news as cards with a visible date window', () => {
    render(<RagVisualizations visualizations={[{
      type: 'news_cards',
      title: '최근 뉴스',
      data: {
        date_from: '2026-07-23',
        date_to: '2026-07-25',
        items: [{
          source_id: 'n1',
          title: '반도체 공급 확대',
          snippet: '공급 계약 관련 핵심 내용',
          publisher: '테스트뉴스',
          published_at: '2026-07-25T09:00:00+09:00',
          url: 'https://example.com/news',
        }],
      },
      sourceIds: ['n1'],
    }]} />)
    expect(screen.getByText('관련 뉴스')).toBeTruthy()
    expect(screen.getByText('1건')).toBeTruthy()
    expect(screen.getByRole('link', { name: /반도체 공급 확대/ }).getAttribute('href')).toBe('https://example.com/news')
  })

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
    expect(screen.getByText('공식 실적')).toBeTruthy()
    expect(screen.getByText('전망')).toBeTruthy()
    expect(screen.getByText('증권사 전망치이며 실제 가격이나 확정 실적이 아닙니다.')).toBeTruthy()
  })

  it('renders news sentiment badge and stock code', () => {
    render(<RagVisualizations visualizations={[{
      type: 'news_cards',
      title: '최근 뉴스',
      data: {
        items: [{ source_id: 'n1', title: '악재 소식', publisher: '테스트', published_at: '2026-07-24T09:00:00+09:00', sentiment: 'negative', stock_code: '005930' }],
      },
      sourceIds: ['n1'],
    }]} />)
    expect(screen.getByText('악재')).toBeTruthy()
    expect(document.querySelector('.news-list-item.is-sentiment-negative')).toBeTruthy()
  })

  it('accepts the cluster sentiment field name defensively', () => {
    render(<RagVisualizations visualizations={[{
      type: 'news_cards',
      title: '최근 뉴스',
      data: {
        items: [{ source_id: 'n1', title: '호재 소식', sentiment_label: 'positive' }],
      },
      sourceIds: ['n1'],
    }]} />)
    expect(screen.getByText('호재')).toBeTruthy()
  })

  it('renders event timeline merging news and disclosures newest-first', () => {
    render(<RagVisualizations visualizations={[{
      type: 'event_timeline',
      title: '관련 사건 타임라인',
      data: {
        events: [
          { kind: 'news', title: '최신 뉴스', at: '2026-07-25T09:00:00+09:00', source_id: 'n1', publisher: '테스트' },
          { kind: 'disclosure', title: '공시 제목', at: '2026-07-21T09:00:00+09:00', source_id: 'd1', publisher: 'DART' },
        ],
      },
      sourceIds: ['n1', 'd1'],
    }]} />)
    expect(screen.getByText('뉴스')).toBeTruthy()
    expect(screen.getByText('공시')).toBeTruthy()
    expect(screen.getByText('최신 뉴스')).toBeTruthy()
  })

  it('draws a price line from many trading-day points without recomputing', () => {
    const points = Array.from({ length: 22 }, (_, i) => ({
      trading_day: `2026-07-${String(i + 1).padStart(2, '0')}`,
      close: 250000 + i * 1000,
      currency: 'KRW',
    }))
    render(<RagVisualizations visualizations={[{
      type: 'price_line',
      title: '실제 주가 흐름',
      data: { points, quote: { currency: 'KRW' }, period: { start_trading_day: '2026-07-01', end_trading_day: '2026-07-22', return_pct: 8.4 } },
      sourceIds: ['price:x'],
    }]} />)
    expect(screen.getByRole('img', { name: /주가 흐름/ })).toBeTruthy()
    expect(screen.getByText('271,000원')).toBeTruthy()
  })

  it('labels a stale closed-session quote as the latest trade instead of current price', () => {
    render(<RagVisualizations visualizations={[{
      type: 'price_snapshot',
      title: '실제 주가',
      data: {
        quote: {
          price: 1525000,
          currency: 'KRW',
          trading_day: '2026-07-28',
          as_of: '2026-07-28T19:59:59+09:00',
          price_kind: 'latest',
          market_status: 'closed',
        },
        period: null,
      },
      sourceIds: ['price:000660:2026-07-28'],
    }]} />)
    expect(screen.getByText('최근 체결가')).toBeTruthy()
    expect(screen.queryByText('현재가')).toBeNull()
  })

  it('labels the final price-line point as the latest trade when the backend says latest', () => {
    render(<RagVisualizations visualizations={[{
      type: 'price_line',
      title: '2026-07-27 ~ 2026-07-28 주가',
      data: {
        points: [
          { trading_day: '2026-07-27', close: 1800000 },
          { trading_day: '2026-07-28', close: 1525000, price_kind: 'latest' },
        ],
        quote: { price: 1525000, currency: 'KRW', price_kind: 'latest' },
        period: { end_price_kind: 'latest' },
      },
      sourceIds: ['price:000660:2026-07-28'],
    }]} />)
    expect(screen.getByText('2026-07-28 최근 체결가')).toBeTruthy()
  })

  it('renders the current event-return horizon contract', () => {
    render(<RagVisualizations visualizations={[{
      type: 'event_return',
      title: '발표 전후 주가 변화',
      data: {
        event_date: '2026-07-20',
        baseline_trading_day: '2026-07-17',
        baseline_close: 85000,
        currency: 'KRW',
        horizons: [
          { horizon_days: 1, trading_day: '2026-07-21', close: 87000, return_pct: 2.35 },
          { horizon_days: 3, trading_day: '2026-07-23', close: 89000, return_pct: 4.7 },
        ],
        daily_full: [
          { trading_day: '2026-07-17', open: 84500, high: 85500, low: 84000, close: 85000, volume: 1000 },
          { trading_day: '2026-07-21', open: 85000, high: 87500, low: 84800, close: 87000, volume: 1200 },
          { trading_day: '2026-07-23', open: 87200, high: 89500, low: 87000, close: 89000, volume: 900 },
        ],
      },
      sourceIds: ['n1', 'p1'],
    }]} />)
    expect(screen.getByText('85,000원')).toBeTruthy()
    expect(screen.getByText('발표 후 1거래일')).toBeTruthy()
    expect(screen.getByText('+4.7%')).toBeTruthy()
    expect(screen.getByRole('img', { name: /발표 전후 토스증권 주가 흐름/ })).toBeTruthy()
    expect(screen.getByText('실제 일봉')).toBeTruthy()
  })

  it('falls back to the matched source URL for a news card', () => {
    render(<RagVisualizations
      sources={[{
        sourceId: 'n1',
        sourceType: 'news_event',
        title: '연결된 뉴스',
        url: 'https://example.com/source-news',
        locator: {},
      }]}
      visualizations={[{
        type: 'news_cards',
        title: '최근 뉴스',
        data: { items: [{ source_id: 'n1', title: '연결된 뉴스' }] },
        sourceIds: ['n1'],
      }]}
    />)
    expect(screen.getByRole('link', { name: /연결된 뉴스/ }).getAttribute('href'))
      .toBe('https://example.com/source-news')
  })

  it('does not send a news card to an unrelated search when no cluster id exists', () => {
    render(<RagVisualizations visualizations={[{
      type: 'news_cards',
      title: '최근 뉴스',
      data: { items: [{ source_id: 'n1', title: '원문 주소가 없는 뉴스' }] },
      sourceIds: ['n1'],
    }]} />)
    expect(screen.queryByRole('link', { name: /원문 주소가 없는 뉴스/ })).toBeNull()
  })

  it('routes a RAG news card to the matching in-product cluster', () => {
    render(<RagVisualizations visualizations={[{
      type: 'news_cards',
      title: '최근 뉴스',
      data: { items: [{ source_id: 'news_cluster:7123', title: '클러스터 뉴스' }] },
      sourceIds: ['news_cluster:7123'],
    }]} />)
    const link = screen.getByRole('link', { name: /클러스터 뉴스/ })
    expect(link.getAttribute('href')).toBe('/news?cluster=7123')
    expect(link.getAttribute('target')).toBeNull()
  })

  it('ignores unknown visualization types safely', () => {
    const { container } = render(<RagVisualizations visualizations={[{
      // @ts-expect-error unknown type on purpose
      type: 'unknown_kind', title: 'x', data: {}, sourceIds: ['s1'],
    }]} />)
    expect(container.querySelector('.answer-visuals')?.children).toHaveLength(0)
  })
})
