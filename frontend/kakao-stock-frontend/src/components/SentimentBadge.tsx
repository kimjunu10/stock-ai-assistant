import type { Sentiment } from '../types'

interface SentimentBadgeProps {
  score?: number
  sentiment: Sentiment
  variant?: 'compact' | 'prominent'
}

const COMPACT_LABELS: Record<Sentiment, string> = {
  positive: '호재성',
  negative: '악재성',
  neutral: '중립',
}

const PROMINENT_LABELS: Record<Sentiment, string> = {
  positive: '호재',
  negative: '악재',
  neutral: '중립',
}

const SUMMARY_COPY: Record<Sentiment, { description: string; headline: string }> = {
  positive: {
    headline: '이 뉴스는 호재로 분석됐어요',
    description: '기업에 긍정적인 내용이 담긴 뉴스예요.',
  },
  negative: {
    headline: '이 뉴스는 악재로 분석됐어요',
    description: '기업에 부정적인 내용이 담긴 뉴스예요.',
  },
  neutral: {
    headline: '이 뉴스는 중립으로 분석됐어요',
    description: '기업에 미치는 방향이 뚜렷하지 않은 뉴스예요.',
  },
}

export function SentimentBadge({ score, sentiment, variant = 'compact' }: SentimentBadgeProps) {
  const description = '뉴스 내용의 기업 관련 긍정·중립·부정 방향을 분석한 결과이며 실제 주가 움직임을 예측하지 않습니다.'
  const label = variant === 'prominent' ? PROMINENT_LABELS[sentiment] : COMPACT_LABELS[sentiment]
  return (
    <span
      aria-label={`${label}. ${description}`}
      className={`sentiment-badge sentiment-badge--${sentiment} sentiment-badge--${variant}`}
      title={description}
    >
      <span className="sentiment-badge__dot" />
      {label}
      {typeof score === 'number' && <span>{Math.round(score * 100)}%</span>}
    </span>
  )
}

export function SentimentSummary({ score, sentiment }: Omit<SentimentBadgeProps, 'variant'>) {
  const copy = SUMMARY_COPY[sentiment]
  return (
    <div className={`sentiment-summary sentiment-summary--${sentiment}`}>
      <div className="sentiment-summary__header">
        <strong>{copy.headline}</strong>
        {typeof score === 'number' && <span className="sentiment-summary__score">모델 확신도 {Math.round(score * 100)}%</span>}
      </div>
      <p>
        {copy.description} 모델 분석은 완벽하지 않을 수 있으며,
        실제 주가의 상승·하락을 예측하는 뜻은 아니에요.
      </p>
    </div>
  )
}
