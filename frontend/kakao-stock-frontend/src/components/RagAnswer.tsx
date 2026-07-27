import { cleanPublicText } from '../utils/publicText'

interface RagAnswerProps {
  text: string
}

type AnswerBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'ordered' | 'unordered'; items: string[] }

const ORDERED_ITEM = /^\d+[.)]\s+(.+)$/
const UNORDERED_ITEM = /^[-*•]\s+(.+)$/
const EMPHASIS = /(\*\*[^*\n]+\*\*)/g
const LABELED_NOTE = /^(투자자가 볼 점|왜 중요한가|핵심 의미|주의할 점)\s*[:：]\s*(.+)$/
const CLOSING_PARAGRAPH = /^(이런|따라서|즉[,\s]|결국|요약하면|다만|주의할 점)/

function inlineText(value: string) {
  return value.split(EMPHASIS).filter(Boolean).map((part, index) => (
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
      : part
  ))
}

function parseAnswer(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = []
  let paragraph: string[] = []
  let list: Extract<AnswerBlock, { kind: 'ordered' | 'unordered' }> | undefined

  const flushParagraph = () => {
    const value = paragraph.join(' ').trim()
    if (value) blocks.push({ kind: 'paragraph', text: value })
    paragraph = []
  }
  const flushList = () => {
    if (list?.items.length) blocks.push(list)
    list = undefined
  }

  for (const rawLine of cleanPublicText(text, { preserveEmphasis: true }).replace(/\r/g, '').split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }
    const ordered = line.match(ORDERED_ITEM)
    const unordered = line.match(UNORDERED_ITEM)
    const kind = ordered ? 'ordered' : unordered ? 'unordered' : undefined
    if (kind) {
      flushParagraph()
      if (list?.kind !== kind) flushList()
      list ??= { kind, items: [] }
      list.items.push((ordered?.[1] ?? unordered?.[1] ?? '').trim())
      continue
    }
    flushList()
    paragraph.push(line)
  }
  flushParagraph()
  flushList()
  return blocks
}

function structureAnswer(blocks: AnswerBlock[]): AnswerBlock[] {
  const allParagraphs = blocks.every(
    (block): block is Extract<AnswerBlock, { kind: 'paragraph' }> => block.kind === 'paragraph',
  )
  if (!allParagraphs || blocks.length < 3) return blocks

  const paragraphs = blocks.map((block) => block.text)
  const last = paragraphs.at(-1) ?? ''
  const hasClosingParagraph = paragraphs.length >= 4 && (
    CLOSING_PARAGRAPH.test(last) || LABELED_NOTE.test(last)
  )
  const itemEnd = hasClosingParagraph ? -1 : undefined

  return [
    { kind: 'paragraph', text: paragraphs[0] },
    { kind: 'unordered', items: paragraphs.slice(1, itemEnd) },
    ...(hasClosingParagraph ? [{ kind: 'paragraph' as const, text: last }] : []),
  ]
}

export function RagAnswer({ text }: RagAnswerProps) {
  const blocks = structureAnswer(parseAnswer(text))

  return (
    <div className="rag-answer">
      {blocks.map((block, index) => {
        if (block.kind === 'paragraph') {
          const labeledNote = block.text.match(LABELED_NOTE)
          const followsList = index > 0 && blocks[index - 1]?.kind !== 'paragraph'

          if (index === 0 && blocks.length > 1) {
            return (
              <section className="rag-answer__summary" key={`${block.kind}-${index}`}>
                <span>한눈에 보기</span>
                <p>{inlineText(block.text)}</p>
              </section>
            )
          }
          if (labeledNote || followsList) {
            return (
              <section className="rag-answer__note" key={`${block.kind}-${index}`}>
                <span>{labeledNote?.[1] ?? '왜 중요한가'}</span>
                <p>{inlineText(labeledNote?.[2] ?? block.text)}</p>
              </section>
            )
          }
          return <p key={`${block.kind}-${index}`}>{inlineText(block.text)}</p>
        }
        const items = block.items.map((item, itemIndex) => (
          <li key={`${item}-${itemIndex}`}><span>{inlineText(item)}</span></li>
        ))
        return block.kind === 'ordered'
          ? <ol key={`${block.kind}-${index}`}>{items}</ol>
          : <ul key={`${block.kind}-${index}`}>{items}</ul>
      })}
    </div>
  )
}
