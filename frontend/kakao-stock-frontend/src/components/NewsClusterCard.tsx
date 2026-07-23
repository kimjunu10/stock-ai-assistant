import { useRef, useState, type MouseEvent, type SyntheticEvent } from 'react'
import { explainNewsSelection } from '../api/news'
import { getStock } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import { Icon } from './Icon'
import { SelectionExplainer } from './SelectionExplainer'
import { createSelectionAnchor, type SelectionAnchor } from './selectionAnchor'
import { SentimentBadge, SentimentSummary } from './SentimentBadge'
import { StockAvatar } from './StockAvatar'
import { TermUnderline } from './TermUnderline'

const INITIAL_SOURCE_COUNT = 3
const SOURCE_PAGE_SIZE = 5

interface NewsClusterCardProps {
  cluster: NewsCluster
  compact?: boolean
  onAsk?: (context: AssistantContext) => void
  showStock?: boolean
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

function splitSentences(value: string) {
  return value
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean)
}

function factualParagraphs(value: string) {
  const explicitParagraphs = value
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
  if (explicitParagraphs.length > 1) return explicitParagraphs

  const sentences = splitSentences(value)
  if (sentences.length <= 2) return sentences.length ? [sentences.join(' ')] : []
  const paragraphCount = Math.min(3, Math.ceil(sentences.length / 2))
  const paragraphs: string[] = []
  let offset = 0
  for (let index = 0; index < paragraphCount; index += 1) {
    const remainingSentences = sentences.length - offset
    const remainingParagraphs = paragraphCount - index
    const size = Math.ceil(remainingSentences / remainingParagraphs)
    paragraphs.push(sentences.slice(offset, offset + size).join(' '))
    offset += size
  }
  return paragraphs
}

function HighlightedParagraph({ children }: { children: string }) {
  const marked = children.match(/^\*\*(.+?)\*\*\s*(.*)$/s)
  if (marked) {
    return <p><strong>{marked[1]}</strong>{marked[2] ? ` ${marked[2]}` : ''}</p>
  }
  const [lead, ...rest] = splitSentences(children)
  if (!lead) return null
  return <p><strong>{lead}</strong>{rest.length ? ` ${rest.join(' ')}` : ''}</p>
}

export function NewsClusterCard({ cluster, compact = false, onAsk, showStock = false }: NewsClusterCardProps) {
  const stock = getStock(cluster.stockCode)
  const articleRef = useRef<HTMLElement>(null)
  const [copied, setCopied] = useState(false)
  const [selectedText, setSelectedText] = useState<SelectionAnchor | null>(null)
  const [selectionExplanation, setSelectionExplanation] = useState('')
  const [selectionError, setSelectionError] = useState('')
  const [isExplaining, setIsExplaining] = useState(false)
  const [isEasyExplanationOpen, setIsEasyExplanationOpen] = useState(false)
  const [visibleSourceCount, setVisibleSourceCount] = useState(INITIAL_SOURCE_COUNT)
  const sources = cluster.sources ?? []
  const factualBody = cluster.factualBody ?? cluster.easySummary
  const visibleSources = sources.slice(0, visibleSourceCount)
  const hiddenSourceCount = Math.max(0, sources.length - visibleSources.length)

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
    setSelectedText(createSelectionAnchor(range, text))
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
        <SelectionExplainer
          anchor={selectedText}
          error={selectionError}
          explanation={selectionExplanation}
          isLoading={isExplaining}
          onAsk={onAsk ? () => {
            onAsk({ stockCode: cluster.stockCode, sourceType: 'news_cluster', sourceId: String(cluster.id), title: cluster.title, selectedText: selectedText.text })
            setSelectedText(null)
          } : undefined}
          onClose={() => setSelectedText(null)}
          onRequest={requestEasyExplanation}
        />
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
        {cluster.sentiment && <SentimentSummary score={cluster.sentimentScore ?? undefined} sentiment={cluster.sentiment} />}
        <p><EasySummary cluster={cluster} /></p>
      </details>
      <div className="news-card__factual-body">
        <span>사건 정리</span>
        <div>
          {factualParagraphs(factualBody).map((paragraph, index) => (
            <HighlightedParagraph key={`${cluster.id}:paragraph:${index}`}>{paragraph}</HighlightedParagraph>
          ))}
        </div>
      </div>
      {!compact && cluster.sentimentReason && (
        <div className="news-card__reason">
          <span>왜 이렇게 봤나요?</span>
          <p>{cluster.sentimentReason}</p>
        </div>
      )}
      {sources.length > 0 && (
        <details
          className="news-card__sources"
          onToggle={(event) => {
            if (!event.currentTarget.open) setVisibleSourceCount(INITIAL_SOURCE_COUNT)
          }}
        >
          <summary>
            <span>원문 {sources.length}개 보기</span>
            <Icon name="chevron-right" size={14} />
          </summary>
          <div>
            {visibleSources.map((source) => (
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
            {hiddenSourceCount > 0 && (
              <button
                className="news-card__sources-more"
                onClick={() => setVisibleSourceCount((count) => Math.min(count + SOURCE_PAGE_SIZE, sources.length))}
                type="button"
              >
                원문 {Math.min(SOURCE_PAGE_SIZE, hiddenSourceCount)}개 더보기
                <span>{visibleSources.length}/{sources.length}</span>
                <Icon name="chevron-right" size={14} />
              </button>
            )}
          </div>
        </details>
      )}
      <div className="news-card__footer">
        <span>
          기사 {cluster.articleCount}건
          {cluster.pressList.length > 0 && ` · 언론사 ${cluster.pressList.length}곳`}
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
