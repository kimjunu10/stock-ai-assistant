import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useRagConversation } from '../hooks/useRagConversation'
import type { RagContext, RagSource, RagSourceType } from '../types/qa'
import { Icon } from './Icon'
import { RagVisualizations } from './RagVisualizations'

interface RagConversationProps {
  context: RagContext
  emptyTitle?: string
  variant: 'page' | 'panel'
}

const SOURCE_LABELS: Record<RagSourceType, string> = {
  financial: '공식 재무정보',
  term: '금융용어 출처',
  news_event: '언론 보도',
  dart_document: 'DART 공시',
  structured_disclosure: 'DART 구조화 공시',
  research_report: '증권사 전망',
  price: '실제 시장 가격',
}

function suggestions(context: RagContext) {
  if (context.sourceType === 'news_event') return ['이 사건이 왜 중요해?', '발표 전후 주가는 어떻게 움직였어?', '관련된 공식 공시가 있어?', '후속 보도가 있었어?']
  if (context.sourceType === 'dart_document' || context.sourceType === 'structured_disclosure') return ['이 공시 핵심 숫자만 알려줘', '투자자가 주의할 점은 뭐야?', '관련 뉴스가 있어?', '정정 전과 후 무엇이 달라졌어?']
  if (context.sourceType === 'research_report') return ['이 리포트의 목표주가와 근거는?', '실제 실적과 전망치를 비교해줘', '다른 증권사 의견과 비교해줘', '회사 발표 내용만 알려줘']
  return ['이 종목 지금 핵심만 정리해줘', '최근 주가가 어떻게 움직였어?', '최근 호재만 알려줘. 실적 관련은 제외해.', '실제 실적과 증권사 전망을 비교해줘.']
}

function contextLabel(context: RagContext) {
  const stock = context.stockName ?? context.stockCode
  if (context.sourceType === 'news_event') return `${stock ? `${stock} · ` : ''}현재 뉴스 기준`
  if (context.sourceType === 'dart_document' || context.sourceType === 'structured_disclosure') return `${stock ? `${stock} · ` : ''}현재 공시 기준`
  if (context.sourceType === 'research_report') return `${stock ? `${stock} · ` : ''}현재 리포트${context.page ? ` ${context.page}페이지` : ''} 기준`
  return stock ? `${stock} 기준` : '전체 자료 기준'
}

function sourceHref(source: RagSource) {
  if (source.url) return source.url
  return undefined
}

function SourceCards({ sources }: { sources: RagSource[] }) {
  if (sources.length === 0) return null
  return (
    <section aria-label="답변 출처" className="rag-sources">
      <h3>확인한 출처 <span>{sources.length}</span></h3>
      <div>
        {sources.map((source) => {
          const href = sourceHref(source)
          const content = (
            <>
              <span>{SOURCE_LABELS[source.sourceType]}</span>
              <strong>{source.title ?? '제목 없는 출처'}</strong>
              <small>{[source.publisher, source.publishedAt, source.page ? `${source.page}페이지` : ''].filter(Boolean).join(' · ')}</small>
              {source.valueKind && <em>{source.valueKind === 'forecast' ? '전망값' : '실제값'}</em>}
              {href && <Icon name="external" size={14} />}
            </>
          )
          return href
            ? <a href={href} key={source.sourceId} rel="noreferrer" target="_blank">{content}</a>
            : <article key={source.sourceId}>{content}</article>
        })}
      </div>
    </section>
  )
}

export function RagConversation({ context, emptyTitle, variant }: RagConversationProps) {
  const [input, setInput] = useState('')
  const { abort, messages, phase, progress, reset, retry, send } = useRagConversation(context)
  const scrollRef = useRef<HTMLDivElement>(null)
  const starterQuestions = useMemo(() => suggestions(context), [context])
  const active = phase === 'connecting' || phase === 'running' || phase === 'streaming'

  useEffect(() => {
    if (messages.length > 0 || progress) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [messages, progress])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim() || active) return
    void send(input)
    setInput('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <div className={`rag-conversation rag-conversation--${variant}`}>
      <div aria-live="polite" className="rag-thread" ref={scrollRef}>
        <div className="rag-context-badge"><Icon name="sparkles" size={14} /><span>{contextLabel(context)}</span></div>
        {context.title && <div className="rag-context-title"><strong>{context.title}</strong>{context.selectedText && <q>{context.selectedText}</q>}</div>}

        {messages.length === 0 ? (
          <div className="rag-empty">
            <span><Icon name="message" size={25} /></span>
            <h1>{emptyTitle ?? '무엇이 궁금한가요?'}</h1>
            <p>뉴스·공시·리포트·재무·실제 주가를 찾아<br />확인된 근거와 함께 답해요.</p>
            <div className="rag-starters">
              {starterQuestions.map((question) => <button key={question} onClick={() => void send(question)} type="button">{question}<Icon name="arrow-right" size={15} /></button>)}
            </div>
          </div>
        ) : (
          <div className="rag-messages">
            {messages.map((message) => (
              <article className={`rag-message rag-message--${message.role}${message.state ? ` is-${message.state}` : ''}`} key={message.id}>
                {message.role === 'assistant' && <span className="chat-avatar" aria-hidden="true">M</span>}
                <div>
                  {message.text
                    ? <p>{message.text}</p>
                    : message.state === 'pending' && <span className="rag-answer-placeholder">근거를 확인하고 있어요…</span>}
                  {message.role === 'assistant' && <RagVisualizations visualizations={message.visualizations} />}
                  {message.role === 'assistant' && <SourceCards sources={message.sources} />}
                  {message.warnings.length > 0 && <div className="rag-warnings">{message.warnings.map((warning) => <p key={warning}><Icon name="info" size={13} />{warning}</p>)}</div>}
                  {(message.state === 'error' || message.state === 'aborted') && <button className="rag-retry" onClick={retry} type="button"><Icon name="refresh" size={14} /> 다시 시도</button>}
                </div>
              </article>
            ))}
          </div>
        )}
        {active && <div className="rag-progress" role="status"><i /><span>{progress}</span></div>}
      </div>

      <form className="rag-composer" onSubmit={submit}>
        <div>
          <textarea
            aria-label={`${context.stockName ?? context.stockCode ?? ''} AI 질문 입력`}
            disabled={active}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="AI에게 질문해 보세요"
            rows={2}
            value={input}
          />
          {active
            ? <button aria-label="답변 생성 중단" className="rag-stop" onClick={abort} type="button"><span /></button>
            : <button aria-label="질문 보내기" disabled={!input.trim()} type="submit"><Icon name="send" size={17} /></button>}
        </div>
        <footer>
          <span><Icon name="document" size={13} /> Agentic Hybrid RAG</span>
          {messages.length > 0 && !active && <button onClick={reset} type="button">새 질문</button>}
        </footer>
      </form>
    </div>
  )
}
