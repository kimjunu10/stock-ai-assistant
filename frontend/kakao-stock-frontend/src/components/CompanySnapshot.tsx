import type { Stock, StockCompanyProfile, StockMarketData } from '../types'
import { Icon } from './Icon'

interface CompanySnapshotProps {
  marketData: StockMarketData | null
  profile: StockCompanyProfile | null
  stock: Stock
}

const numberFormatter = new Intl.NumberFormat('ko-KR')

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ko-KR', {
    day: 'numeric',
    month: 'long',
    timeZone: 'Asia/Seoul',
    year: 'numeric',
  }).format(new Date(`${value}T00:00:00+09:00`))
}

function formatLargeWon(value: number | null) {
  if (value === null) return '—'
  const eok = Math.round(value / 100_000_000)
  const jo = Math.floor(eok / 10_000)
  const remainder = eok % 10_000
  if (jo > 0 && remainder > 0) return `${numberFormatter.format(jo)}조 ${numberFormatter.format(remainder)}억원`
  if (jo > 0) return `${numberFormatter.format(jo)}조원`
  return `${numberFormatter.format(remainder)}억원`
}

export function CompanySnapshot({ marketData, profile, stock }: CompanySnapshotProps) {
  const marketCap = marketData?.quote.price && profile?.sharesOutstanding
    ? marketData.quote.price * profile.sharesOutstanding
    : null

  return (
    <div className="company-snapshot">
      <div className="company-snapshot__intro">
        <div>
          <span>{profile?.market ?? stock.market} · {stock.code}</span>
          <h3>{profile?.name ?? stock.name}</h3>
          <p>출처: DART 기업개황 · 토스증권 종목 정보</p>
        </div>
        {profile?.homepage && (
          <a href={profile.homepage} rel="noreferrer" target="_blank">
            홈페이지 <Icon name="external" size={15} />
          </a>
        )}
      </div>
      <p className="company-snapshot__description">{stock.summary}이에요.</p>
      <dl className="company-snapshot__facts">
        <div>
          <dt>시가총액</dt>
          <dd>{formatLargeWon(marketCap)}</dd>
          <small>현재가 × 발행주식수</small>
        </div>
        <div>
          <dt>대표이사</dt>
          <dd>{profile?.ceo ?? '—'}</dd>
          <small>DART 기업개황</small>
        </div>
        <div>
          <dt>상장일</dt>
          <dd>{formatDate(profile?.listDate)}</dd>
          <small>설립 {formatDate(profile?.establishedDate)}</small>
        </div>
        <div>
          <dt>발행주식수</dt>
          <dd>{profile?.sharesOutstanding ? `${numberFormatter.format(profile.sharesOutstanding)}주` : '—'}</dd>
          <small>토스증권 종목 정보</small>
        </div>
      </dl>
    </div>
  )
}
