import { getStock } from '../data/mockData'
import { cleanPublicText } from '../utils/publicText'
import { Icon } from './Icon'
import { SentimentBadge } from './SentimentBadge'

interface RagNewsResultItemProps {
  publishedAt?: string
  publisher?: string
  sentiment?: 'negative' | 'neutral' | 'positive'
  snippet?: string
  stockCode?: string
  title: string
  url?: string
}

function publishedText(value?: string) {
  if (!value) return '날짜 미상'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'long',
    day: 'numeric',
    timeZone: 'Asia/Seoul',
  }).format(parsed)
}

function conciseText(value: string, limit = 180) {
  const cleaned = cleanPublicText(value).replace(/\s+/g, ' ').trim()
  return cleaned.length > limit ? `${cleaned.slice(0, limit).trimEnd()}…` : cleaned
}

export function RagNewsResultItem({
  publishedAt,
  publisher,
  sentiment,
  snippet,
  stockCode,
  title,
  url,
}: RagNewsResultItemProps) {
  const stock = stockCode ? getStock(stockCode) : undefined
  const content = (
    <>
      <span className="news-list-item__thumbnail">
        {stock
          ? <img alt="" className="is-fallback" src={stock.imageSrc} />
          : <Icon name="news" size={24} />}
      </span>
      <span className="news-list-item__content">
        <span className="news-list-item__eyebrow">
          <span>{publisher || '언론 보도'}</span>
          <time>{publishedText(publishedAt)}</time>
          {sentiment && (
            <span className="news-list-item__sentiment">
              <SentimentBadge sentiment={sentiment} variant="prominent" />
            </span>
          )}
        </span>
        <strong className="news-list-item__title">{conciseText(title, 100)}</strong>
        {snippet && <span className="news-list-item__body-preview">{conciseText(snippet)}</span>}
      </span>
      {url && <Icon className="news-list-item__arrow" name="external" size={17} />}
    </>
  )

  return (
    <article className={[
      'news-list-item',
      'answer-news-item',
      sentiment ? `is-sentiment-${sentiment}` : '',
    ].filter(Boolean).join(' ')}>
      {url
        ? <a className="news-list-item__button" href={url} rel="noreferrer" target="_blank">{content}</a>
        : <div className="news-list-item__button">{content}</div>}
    </article>
  )
}
