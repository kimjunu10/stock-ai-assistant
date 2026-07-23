import type { Sentiment } from '../types'

interface SentimentBadgeProps {
  score?: number
  sentiment: Sentiment
}

const LABELS: Record<Sentiment, string> = {
  positive: '호재성',
  negative: '악재성',
  neutral: '중립',
}

export function SentimentBadge({ score, sentiment }: SentimentBadgeProps) {
  const description = '뉴스 내용의 기업 관련 긍정·중립·부정 방향을 분석한 결과이며 실제 주가 움직임을 예측하지 않습니다.'
  return (
    <span
      aria-label={`${LABELS[sentiment]}. ${description}`}
      className={`sentiment-badge sentiment-badge--${sentiment}`}
      title={description}
    >
      <span className="sentiment-badge__dot" />
      {LABELS[sentiment]}
      {typeof score === 'number' && <span>{Math.round(score * 100)}%</span>}
    </span>
  )
}
