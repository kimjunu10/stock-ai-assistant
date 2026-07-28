import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { cleanPublicText } from '../utils/publicText'
import { RagAnswer } from './RagAnswer'

describe('RagAnswer', () => {
  it('turns numbered prose into a semantic list without rendering HTML', () => {
    render(<RagAnswer text={'핵심만 정리하면 다음과 같습니다.\n\n1. 첫 번째 소식\n2. <script>alert(1)</script>'} />)
    expect(screen.getByText('핵심만 정리하면 다음과 같습니다.')).toBeTruthy()
    expect(screen.getByRole('list').tagName).toBe('OL')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('<script>alert(1)</script>')).toBeTruthy()
    expect(document.querySelector('script')).toBeNull()
  })

  it('removes internal data labels from public copy', () => {
    expect(cleanPublicText('연결 · actual_value / forecast_value')).toBe('연결 · 실제 실적 / 전망')
  })

  it('removes internal source ids from answer copy', () => {
    expect(cleanPublicText('협약을 체결했습니다. (출처: news_cluster:7104)')).toBe('협약을 체결했습니다.')
  })

  it('renders only marked key facts with strong emphasis', () => {
    render(<RagAnswer text={'핵심은 **현재가 252,500원**입니다.\n- 전일 대비 **+1.20%**'} />)
    expect(screen.getByText('현재가 252,500원').tagName).toBe('STRONG')
    expect(screen.getByText('+1.20%').tagName).toBe('STRONG')
  })

  it('turns unstructured multi-paragraph prose into a summary, points, and a callout', () => {
    const view = render(<RagAnswer text={[
      '호재는 생산 능력 확대와 제품 경쟁력 강화에 집중돼 있습니다.',
      '',
      '청주에 반도체 연구 인프라를 구축합니다.',
      '',
      '폴더블폰 두께를 10% 줄였습니다.',
      '',
      'HBM5의 동작 속도를 높였습니다.',
      '',
      '이런 변화는 기술력과 생산성 개선 여부를 확인할 신호입니다.',
    ].join('\n')} />)

    const answer = within(view.container)
    expect(answer.getByText('한눈에 보기')).toBeTruthy()
    expect(answer.getAllByRole('listitem')).toHaveLength(3)
    expect(answer.getByText('왜 중요한가')).toBeTruthy()
  })

  it('renders an explicit investor takeaway as a labeled callout', () => {
    const view = render(<RagAnswer text={'핵심 흐름입니다.\n- 첫 번째 근거\n투자자가 볼 점: 실제 매출로 이어지는지 확인해야 합니다.'} />)

    const answer = within(view.container)
    expect(answer.getByText('투자자가 볼 점')).toBeTruthy()
    expect(answer.getByText('실제 매출로 이어지는지 확인해야 합니다.')).toBeTruthy()
  })

  it('breaks a long single paragraph into a summary and readable points', () => {
    const view = render(<RagAnswer text={[
      '이 뉴스는 레버리지 상품의 신용거래 위험이 커졌다는 내용입니다.',
      '관련 상품 거래가 늘면서 담보 가치가 빠르게 변할 수 있습니다.',
      '반대매매가 증가하면 주가 변동성도 함께 커질 수 있습니다.',
      '투자자는 상품 구조와 손실 가능성을 먼저 확인해야 합니다.',
    ].join(' ')} />)

    const answer = within(view.container)
    expect(answer.getByText('한눈에 보기')).toBeTruthy()
    expect(answer.getAllByRole('listitem')).toHaveLength(3)
  })
})
