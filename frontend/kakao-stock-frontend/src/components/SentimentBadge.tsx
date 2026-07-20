import type { Sentiment } from '../types'

interface SentimentBadgeProps {
  score?: number
  sentiment: Sentiment
}

const LABELS: Record<Sentiment, string> = {
  positive: '호재',
  negative: '악재',
  neutral: '중립',
}

export function SentimentBadge({ score, sentiment }: SentimentBadgeProps) {
  return (
    <span className={`sentiment-badge sentiment-badge--${sentiment}`}>
      <span className="sentiment-badge__dot" />
      {LABELS[sentiment]}
      {typeof score === 'number' && <span>{Math.round(score * 100)}%</span>}
    </span>
  )
}
