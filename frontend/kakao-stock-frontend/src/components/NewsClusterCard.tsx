import { useRef, useState, type MouseEvent, type SyntheticEvent } from 'react'
import { explainNewsSelection } from '../api/news'
import { getStock } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import { Icon } from './Icon'
import { SentimentBadge } from './SentimentBadge'
import { StockAvatar } from './StockAvatar'
import { TermUnderline } from './TermUnderline'

interface NewsClusterCardProps {
  cluster: NewsCluster
  compact?: boolean
  onAsk?: (context: AssistantContext) => void
  showStock?: boolean
}

interface SelectedText {
  left: number
  text: string
  top: number
}

function EasySummary({ cluster }: { cluster: NewsCluster }) {
  const term = cluster.terms?.[0]
  if (!term || !cluster.easySummary.includes(term.term)) {
    return <>{cluster.easySummary}</>
  }

  const [before, after] = cluster.easySummary.split(term.term)
  return (
    <>
      {before}
      <TermUnderline definition={term.easyDefinition} term={term.term} />
      {after}
    </>
  )
}

function formatPublishedAt(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed)
}

function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime()
  if (Number.isNaN(timestamp)) return ''
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000))
  if (elapsedMinutes < 1) return '방금 전'
  if (elapsedMinutes < 60) return `${elapsedMinutes}분 전`
  const elapsedHours = Math.floor(elapsedMinutes / 60)
  if (elapsedHours < 24) return `${elapsedHours}시간 전`
  const elapsedDays = Math.floor(elapsedHours / 24)
  if (elapsedDays < 30) return `${elapsedDays}일 전`
  return formatPublishedAt(value)
}

function publisherFallbackImage(url: string) {
  try {
    return `${new URL(url).origin}/favicon.ico`
  } catch {
    return ''
  }
}

export function NewsClusterCard({ cluster, compact = false, onAsk, showStock = false }: NewsClusterCardProps) {
  const stock = getStock(cluster.stockCode)
  const articleRef = useRef<HTMLElement>(null)
  const [copied, setCopied] = useState(false)
  const [selectedText, setSelectedText] = useState<SelectedText | null>(null)
  const [selectionExplanation, setSelectionExplanation] = useState('')
  const [selectionError, setSelectionError] = useState('')
  const [isExplaining, setIsExplaining] = useState(false)
  const [isEasyExplanationOpen, setIsEasyExplanationOpen] = useState(true)
  const sources = cluster.sources ?? []

  const copySummary = async () => {
    try {
      await navigator.clipboard.writeText(
        `${cluster.title}\n\n${cluster.easySummary}\n\n${cluster.factualBody ?? ''}`,
      )
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  const handleTextSelection = (event: MouseEvent<HTMLElement>) => {
    if ((event.target as Element).closest('button, a, summary')) return
    const selection = window.getSelection()
    const article = articleRef.current
    if (!selection || selection.isCollapsed || !article || selection.rangeCount === 0) {
      setSelectedText(null)
      return
    }
    const text = selection.toString().replace(/\s+/g, ' ').trim()
    if (text.length < 2) return
    const range = selection.getRangeAt(0)
    const ancestor = range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentElement
      : range.commonAncestorContainer as Element
    if (!ancestor || !article.contains(ancestor)) return
    const rangeRects = Array.from(range.getClientRects())
    const rangeRect = rangeRects.at(-1) ?? range.getBoundingClientRect()
    const articleRect = article.getBoundingClientRect()
    setSelectedText({
      text: text.slice(0, 500),
      top: Math.max(8, rangeRect.top - articleRect.top - 38),
      left: Math.min(
        Math.max(12, rangeRect.right - articleRect.left - 18),
        articleRect.width - 48,
      ),
    })
    setSelectionExplanation('')
    setSelectionError('')
  }

  const handleSourceImageError = (event: SyntheticEvent<HTMLImageElement>, sourceUrl: string) => {
    const image = event.currentTarget
    const fallback = publisherFallbackImage(sourceUrl)
    if (fallback && image.src !== fallback) {
      image.src = fallback
      image.classList.add('is-fallback')
      return
    }
    image.hidden = true
  }

  const requestEasyExplanation = async () => {
    if (!selectedText || isExplaining) return
    setIsExplaining(true)
    setSelectionError('')
    try {
      const response = await explainNewsSelection(cluster.id, selectedText.text)
      setSelectionExplanation(response.explanation)
    } catch (reason: unknown) {
      setSelectionError(reason instanceof Error ? reason.message : '선택한 문구를 설명하지 못했어요.')
    } finally {
      setIsExplaining(false)
    }
  }

  return (
    <article
      className={compact ? 'news-card news-card--compact' : 'news-card'}
      id={`news_cluster:${cluster.id}`}
      onMouseUp={handleTextSelection}
      ref={articleRef}
    >
      {selectedText && (
        <div className="selection-explainer" style={{ left: selectedText.left, top: selectedText.top }}>
          <button
            aria-label="선택한 문구 쉽게 설명"
            className="selection-explainer__trigger"
            onClick={requestEasyExplanation}
            onMouseDown={(event) => event.preventDefault()}
            type="button"
          >
            <Icon name="sparkles" size={16} />
          </button>
          {(isExplaining || selectionExplanation || selectionError) && (
            <div className="selection-explainer__popover">
              <div><span>AI 쉬운 설명</span><button aria-label="쉬운 설명 닫기" onClick={() => setSelectedText(null)} type="button"><Icon name="close" size={14} /></button></div>
              <strong>“{selectedText.text}”</strong>
              <p>{isExplaining ? '쉽게 풀어 쓰고 있어요…' : selectionExplanation || selectionError}</p>
            </div>
          )}
        </div>
      )}
      <div className="news-card__meta-row">
        <div className="news-card__badges">
          {cluster.sentiment && (
            <SentimentBadge score={cluster.sentimentScore ?? undefined} sentiment={cluster.sentiment} />
          )}
          {showStock && stock && (
            <span className="news-card__stock">
              <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />
              {stock.name}
            </span>
          )}
        </div>
        <div className="news-card__tools">
          <time>{formatPublishedAt(cluster.publishedAt)}</time>
          <button aria-label="뉴스 정리 복사" className="news-card__copy" onClick={copySummary} type="button">
            <Icon name={copied ? 'check' : 'copy'} size={15} />
          </button>
        </div>
      </div>
      <h3>{cluster.title}</h3>
      <details
        className="news-card__easy-explanation"
        onToggle={(event) => setIsEasyExplanationOpen(event.currentTarget.open)}
        open={isEasyExplanationOpen}
      >
        <summary>
          <span><Icon name="sparkles" size={14} /> AI 쉬운 설명</span>
          <span className="news-card__easy-toggle"><span>접기</span><Icon name="chevron-right" size={14} /></span>
        </summary>
        <p><EasySummary cluster={cluster} /></p>
      </details>
      <div className="news-card__factual-body">
        <span>사건 정리</span>
        <p>{cluster.factualBody ?? cluster.easySummary}</p>
      </div>
      {!compact && cluster.sentimentReason && (
        <div className="news-card__reason">
          <span>왜 이렇게 봤나요?</span>
          <p>{cluster.sentimentReason}</p>
        </div>
      )}
      {sources.length > 0 && (
        <details className="news-card__sources">
          <summary>원문 보기</summary>
          <div>
            {sources.map((source) => (
              <a href={source.url} key={source.articleId} rel="noreferrer" target="_blank">
                <span className="news-card__source-image">
                  <img
                    alt=""
                    className={source.imageUrl ? undefined : 'is-fallback'}
                    onError={(event) => handleSourceImageError(event, source.url)}
                    src={source.imageUrl || publisherFallbackImage(source.url)}
                  />
                </span>
                <span className="news-card__source-content">
                  <span className="news-card__source-meta">
                    <strong>{source.press}</strong>
                    <span aria-hidden="true">·</span>
                    <time dateTime={source.publishedAt} title={formatPublishedAt(source.publishedAt)}>
                      {formatRelativeTime(source.publishedAt)}
                    </time>
                  </span>
                  <strong className="news-card__source-title">{source.title}</strong>
                  {source.description && <span className="news-card__source-description">{source.description}</span>}
                </span>
                <Icon className="news-card__source-external" name="external" size={15} />
              </a>
            ))}
          </div>
        </details>
      )}
      <div className="news-card__footer">
        <span>
          기사 {cluster.articleCount}건
          {cluster.pressList.length > 0 && (
            <span className="news-card__press-list"> · {cluster.pressList.join(' · ')}</span>
          )}
        </span>
        {onAsk && (
          <button
            className="text-button"
            onClick={() =>
              onAsk({
                stockCode: cluster.stockCode,
                sourceType: 'news_cluster',
                sourceId: String(cluster.id),
                title: cluster.title,
              })
            }
            type="button"
          >
            <Icon name="message" size={16} />
            이 뉴스 물어보기
          </button>
        )}
      </div>
    </article>
  )
}
