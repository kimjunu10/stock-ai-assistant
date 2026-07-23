import { useEffect, useRef, useState, type MouseEvent, type SyntheticEvent } from 'react'
import { createPortal } from 'react-dom'
import { explainNewsSelection } from '../api/news'
import { getStock } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import { Icon } from './Icon'
import { SelectionExplainer } from './SelectionExplainer'
import { createSelectionAnchor, type SelectionAnchor } from './selectionAnchor'
import { SentimentBadge } from './SentimentBadge'
import { StockAvatar } from './StockAvatar'

const INITIAL_SOURCE_COUNT = 5

interface Props {
  assistantOpen?: boolean
  cluster: NewsCluster
  onAssistantClose?: () => void
  onAsk: (context: AssistantContext) => void
}

function formatPublishedAt(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long', timeStyle: 'short' }).format(parsed)
}

function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime()
  if (Number.isNaN(timestamp)) return value
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000))
  if (minutes < 1) return '방금 전'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}일 전`
  return formatPublishedAt(value)
}

function cleanMarkdown(value: string) {
  return value.replace(/\*\*/g, '').trim()
}

function publisherFallbackImage(url: string) {
  try {
    const origin = new URL(url).origin
    return `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(origin)}&sz=64`
  } catch {
    return ''
  }
}

function PublisherLogos({ cluster }: { cluster: NewsCluster }) {
  const sources = cluster.sources ?? []
  const visible = sources.filter((source, index, items) => items.findIndex((item) => item.press === source.press) === index).slice(0, 4)
  const total = cluster.pressList.length
  return (
    <span className="publisher-stack" title={cluster.pressList.join(', ')}>
      <span className="publisher-stack__logos">
        {visible.map((source) => (
          <span aria-label={source.press} className="publisher-stack__logo" key={source.press} title={source.press}>
            <span>{source.press.slice(0, 1)}</span>
            <img alt="" onError={(event) => { event.currentTarget.hidden = true }} src={publisherFallbackImage(source.url)} />
          </span>
        ))}
      </span>
      <span>{total > visible.length ? `외 ${total - visible.length}곳` : `${total}곳`}</span>
    </span>
  )
}

function paragraphs(value: string) {
  const removeLabel = (item: string) => item.replace(/^(핵심 사실|배경(?: 및 [^:]{1,16})?|조직(?: 및 [^:]{1,16})?|향후 계획|향후 일정(?: 및 불확실성)?):\s*/, '')
  const explicit = cleanMarkdown(value).split(/\n\s*\n/).map((item) => removeLabel(item.trim())).filter(Boolean)
  if (explicit.length > 1) return explicit
  const sentences = cleanMarkdown(value).replace(/\s+/g, ' ').split(/(?<=[.!?])\s+/).filter(Boolean)
  if (sentences.length < 4) return [sentences.join(' ')]
  const midpoint = Math.ceil(sentences.length / 2)
  return [sentences.slice(0, midpoint).join(' '), sentences.slice(midpoint).join(' ')]
}

function NewsClusterDetail({ assistantOpen = false, cluster, onAsk, onClose }: Props & { onClose: () => void }) {
  const stock = getStock(cluster.stockCode)
  const articleRef = useRef<HTMLElement>(null)
  const [sourceCount, setSourceCount] = useState(INITIAL_SOURCE_COUNT)
  const [selectedText, setSelectedText] = useState<SelectionAnchor | null>(null)
  const [explanation, setExplanation] = useState('')
  const [explanationError, setExplanationError] = useState('')
  const [isExplaining, setIsExplaining] = useState(false)
  const sources = cluster.sources ?? []
  const heroImage = sources.find((source) => source.imageUrl)?.imageUrl

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  const handleSelection = (event: MouseEvent<HTMLElement>) => {
    if ((event.target as Element).closest('button, a')) return
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
    setExplanation('')
    setExplanationError('')
  }

  const requestExplanation = async () => {
    if (!selectedText || isExplaining) return
    setIsExplaining(true)
    try {
      const result = await explainNewsSelection(cluster.id, selectedText.text)
      setExplanation(result.explanation)
    } catch (reason: unknown) {
      setExplanationError(reason instanceof Error ? reason.message : '쉽게 설명하지 못했어요.')
    } finally {
      setIsExplaining(false)
    }
  }

  return createPortal(
    <div className={assistantOpen ? 'news-detail-backdrop news-detail-backdrop--with-assistant' : 'news-detail-backdrop'} onMouseDown={(event) => event.target === event.currentTarget && onClose()} role="presentation">
      <article aria-labelledby={`news-detail-title-${cluster.id}`} aria-modal="true" className="news-detail" onMouseUp={handleSelection} ref={articleRef} role="dialog">
        {selectedText && (
          <SelectionExplainer
            anchor={selectedText}
            error={explanationError}
            explanation={explanation}
            isLoading={isExplaining}
            onAsk={() => {
              onAsk({ stockCode: cluster.stockCode, sourceType: 'news_cluster', sourceId: String(cluster.id), title: cluster.title, presentation: 'news_detail', selectedText: selectedText.text })
              setSelectedText(null)
            }}
            onClose={() => setSelectedText(null)}
            onRequest={requestExplanation}
          />
        )}
        <header className="news-detail__header">
          <div className="news-detail__identity">
            {stock && <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />}
            <span>{stock?.name ?? cluster.stockCode}</span>
            <span aria-hidden="true">·</span>
            <time>{formatPublishedAt(cluster.publishedAt)}</time>
          </div>
          <button aria-label="상세 뉴스 닫기" className="news-detail__close" onClick={onClose} type="button"><Icon name="close" size={22} /></button>
          <h2 id={`news-detail-title-${cluster.id}`}>{cluster.title}</h2>
          <div className="news-detail__counts"><span>기사 {sources.length || cluster.articleCount}건</span><span>언론사 {cluster.pressList.length}곳</span></div>
        </header>
        <div className="news-detail__scroll">
          <section className="news-detail__easy">
            <div><Icon name="sparkles" size={17} /><strong>AI 쉬운 설명</strong></div>
            <p>{cluster.easySummary}</p>
          </section>
          <button className={assistantOpen ? 'news-detail__ask is-active' : 'news-detail__ask'} onClick={() => onAsk({ stockCode: cluster.stockCode, sourceType: 'news_cluster', sourceId: String(cluster.id), title: cluster.title, presentation: 'news_detail' })} type="button">
            <Icon name="message" size={17} />
            <span>{assistantOpen ? '이 뉴스에 질문하는 중' : '이 뉴스에 대해 AI에게 질문하기'}</span>
            <Icon name="arrow-right" size={16} />
          </button>
          <section className="news-detail__body">
            <h3>사건 정리</h3>
            {paragraphs(cluster.factualBody ?? cluster.easySummary).map((paragraph, index) => <p key={`${cluster.id}:detail:${index}`}>{paragraph}</p>)}
          </section>
          {heroImage && <img alt="" className="news-detail__hero-image" onError={(event) => { event.currentTarget.hidden = true }} src={heroImage} />}
          <section className="news-detail__sources">
            <div className="news-detail__section-title"><h3>이 사건을 보도한 원문</h3><span>{sources.length}개</span></div>
            <div>
              {sources.slice(0, sourceCount).map((source) => (
                <a href={source.url} key={source.articleId} rel="noreferrer" target="_blank">
                  <span><strong>{source.title}</strong><small>{source.press} · {formatRelativeTime(source.publishedAt)}</small></span>
                  {source.imageUrl ? <img alt="" onError={(event) => { event.currentTarget.hidden = true }} src={source.imageUrl} /> : <Icon name="external" size={17} />}
                </a>
              ))}
            </div>
            {sourceCount < sources.length && <button className="news-detail__more" onClick={() => setSourceCount((count) => Math.min(count + 10, sources.length))} type="button">원문 더보기 ({sourceCount}/{sources.length})</button>}
          </section>
        </div>
      </article>
    </div>,
    document.body,
  )
}

export function NewsClusterListItem({ assistantOpen = false, cluster, onAssistantClose, onAsk }: Props) {
  const [open, setOpen] = useState(false)
  const [easyOpen, setEasyOpen] = useState(false)
  const stock = getStock(cluster.stockCode)
  const representative = cluster.sources?.[0]
  const thumbnail = cluster.sources?.find((source) => source.imageUrl)?.imageUrl ?? stock?.imageSrc

  const handleImageError = (event: SyntheticEvent<HTMLImageElement>) => {
    if (stock?.imageSrc && event.currentTarget.src !== new URL(stock.imageSrc, window.location.href).href) {
      event.currentTarget.src = stock.imageSrc
      event.currentTarget.classList.add('is-fallback')
      return
    }
    event.currentTarget.hidden = true
  }

  return (
    <>
      <article className={easyOpen ? 'news-list-item is-easy-open' : 'news-list-item'}>
        <div
          aria-label={`${cluster.title} 상세 보기`}
          className="news-list-item__button"
          onClick={() => { setEasyOpen(false); setOpen(true) }}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              setEasyOpen(false)
              setOpen(true)
            }
          }}
          role="button"
          tabIndex={0}
        >
          <span className="news-list-item__thumbnail"><img alt="" className={thumbnail === stock?.imageSrc ? 'is-fallback' : undefined} onError={handleImageError} src={thumbnail} /></span>
          <span className="news-list-item__content">
            <span className="news-list-item__eyebrow">
              {stock && <span className="news-list-item__stock"><StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />{stock.name}</span>}
              {cluster.sentiment && <SentimentBadge score={cluster.sentimentScore ?? undefined} sentiment={cluster.sentiment} />}
              <span>기사 {cluster.sources?.length || cluster.articleCount}건</span>
            </span>
            <strong className="news-list-item__title">{cluster.title}</strong>
            <span className="news-list-item__body-preview">{cleanMarkdown(cluster.factualBody ?? '')}</span>
            <span className="news-list-item__lower">
              <button
                aria-expanded={easyOpen}
                className="news-list-item__easy-button"
                onClick={(event) => { event.stopPropagation(); setEasyOpen((value) => !value) }}
                type="button"
              ><Icon name="sparkles" size={13} /> AI 쉽게 보기 <Icon name="chevron-right" size={13} /></button>
              <PublisherLogos cluster={cluster} />
              <time>{formatRelativeTime(representative?.publishedAt ?? cluster.publishedAt)}</time>
            </span>
          </span>
          <Icon className="news-list-item__arrow" name="chevron-right" size={19} />
        </div>
        {easyOpen && (
          <div className="news-list-item__easy-popover">
            <div><span><Icon name="sparkles" size={14} /> AI 쉬운 설명</span><button aria-label="AI 쉬운 설명 닫기" onClick={() => setEasyOpen(false)} type="button"><Icon name="close" size={14} /></button></div>
            <p>{cluster.easySummary}</p>
            <button onClick={() => { setEasyOpen(false); setOpen(true) }} type="button">상세 뉴스에서 이어 읽기 <Icon name="arrow-right" size={14} /></button>
          </div>
        )}
      </article>
      {open && <NewsClusterDetail assistantOpen={assistantOpen} cluster={cluster} onAsk={onAsk} onClose={() => { setOpen(false); if (assistantOpen) onAssistantClose?.() }} />}
    </>
  )
}
