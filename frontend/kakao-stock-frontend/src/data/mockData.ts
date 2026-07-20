import type {
  DisclosureItem,
  FinancialItem,
  NewsCluster,
  ReportItem,
  Stock,
} from '../types'

export const STOCKS: Stock[] = [
  {
    code: '005930',
    name: '삼성전자',
    initials: '삼성',
    imageSrc: '/stocks/samsung-electronics.png',
    market: 'KOSPI',
    sector: '반도체 · 전자제품',
    price: '84,600원',
    change: '+1,200원',
    changeRate: '+1.44%',
    direction: 'up',
    marketCap: '505조 3,400억원',
    volume: '1,521만주',
    summary: '메모리 반도체와 모바일, 가전 사업을 운영하는 종합 전자기업',
  },
  {
    code: '000660',
    name: 'SK하이닉스',
    initials: 'SK',
    imageSrc: '/stocks/sk-hynix.png',
    market: 'KOSPI',
    sector: '반도체',
    price: '228,500원',
    change: '+3,500원',
    changeRate: '+1.56%',
    direction: 'up',
    marketCap: '166조 3,485억원',
    volume: '348만주',
    summary: 'HBM과 D램을 중심으로 성장하는 글로벌 메모리 반도체 기업',
  },
  {
    code: '034020',
    name: '두산에너빌리티',
    initials: '두산',
    imageSrc: '/stocks/doosan-enerbility.png',
    market: 'KOSPI',
    sector: '발전설비 · 원전',
    price: '27,850원',
    change: '-250원',
    changeRate: '-0.89%',
    direction: 'down',
    marketCap: '17조 8,387억원',
    volume: '611만주',
    summary: '원전과 가스터빈, 신재생 발전설비를 공급하는 에너지 기업',
  },
  {
    code: '042660',
    name: '한화오션',
    initials: '한화',
    imageSrc: '/stocks/hanwha-ocean.jpeg',
    market: 'KOSPI',
    sector: '조선 · 방산',
    price: '68,900원',
    change: '+800원',
    changeRate: '+1.17%',
    direction: 'up',
    marketCap: '21조 1,138억원',
    volume: '274만주',
    summary: 'LNG선과 특수선, 해양플랜트를 만드는 종합 조선 기업',
  },
  {
    code: '005380',
    name: '현대차',
    initials: '현대',
    imageSrc: '/stocks/hyundai-motor.jpeg',
    market: 'KOSPI',
    sector: '자동차',
    price: '284,000원',
    change: '0원',
    changeRate: '0.00%',
    direction: 'flat',
    marketCap: '59조 4,730억원',
    volume: '72만주',
    summary: '완성차와 모빌리티 서비스를 전 세계에 제공하는 자동차 기업',
  },
]

export const NEWS_CLUSTERS: NewsCluster[] = [
  {
    id: 101,
    stockCode: '005930',
    title: '차세대 HBM 공급 확대 기대, 주요 고객사 품질 테스트 진행',
    easySummary:
      '쉽게 말해: AI 반도체에 필요한 고성능 메모리를 더 많이 팔 수 있는 단계에 가까워졌다는 소식이에요.',
    sentiment: 'positive',
    sentimentScore: 0.92,
    sentimentReason: '고부가 제품 매출 확대와 수익성 개선 가능성을 높이는 내용이에요.',
    articleCount: 12,
    pressList: ['연합뉴스', '한국경제', '전자신문'],
    publishedAt: '2시간 전',
    terms: [
      {
        term: 'HBM',
        easyDefinition: 'AI 연산에 필요한 데이터를 빠르게 전달하도록 여러 메모리를 쌓은 제품',
      },
    ],
  },
  {
    id: 102,
    stockCode: '005930',
    title: '스마트폰 출하량 전망 유지, 부품 원가 부담은 변수',
    easySummary:
      '쉽게 말해: 판매 예상은 그대로지만 부품값이 오르면 한 대를 팔아 남는 돈이 줄 수 있어요.',
    sentiment: 'neutral',
    sentimentScore: 0.67,
    sentimentReason: '판매 안정성과 비용 부담이 함께 언급돼 방향을 단정하기 어려워요.',
    articleCount: 7,
    pressList: ['서울경제', '이데일리'],
    publishedAt: '5시간 전',
  },
  {
    id: 103,
    stockCode: '005930',
    title: '반도체 공정 전환 일정 일부 지연 가능성 제기',
    easySummary:
      '쉽게 말해: 새 공정의 생산 안정화가 예상보다 늦어지면 당분간 비용이 더 들 수 있다는 뜻이에요.',
    sentiment: 'negative',
    sentimentScore: 0.81,
    sentimentReason: '생산 일정 지연은 원가와 공급 계획에 부담이 될 수 있어요.',
    articleCount: 5,
    pressList: ['머니투데이', '디지털데일리'],
    publishedAt: '어제',
  },
  {
    id: 201,
    stockCode: '000660',
    title: 'HBM 생산능력 확대 계획 재확인, 내년 물량 협의 진행',
    easySummary:
      '쉽게 말해: 수요가 빠르게 늘어나는 AI용 메모리를 더 만들 준비를 이어가고 있어요.',
    sentiment: 'positive',
    sentimentScore: 0.89,
    sentimentReason: '판매 물량 증가 기대가 실적 성장 가능성을 높여요.',
    articleCount: 10,
    pressList: ['매일경제', '조선비즈'],
    publishedAt: '1시간 전',
    terms: [
      {
        term: '생산능력',
        easyDefinition: '정해진 기간 안에 제품을 얼마나 많이 만들 수 있는지를 뜻해요.',
      },
    ],
  },
  {
    id: 202,
    stockCode: '000660',
    title: '메모리 가격 상승세 둔화 전망 엇갈려',
    easySummary:
      '쉽게 말해: 메모리 가격이 계속 오를지에 대해 시장의 의견이 나뉘고 있어요.',
    sentiment: 'neutral',
    sentimentScore: 0.62,
    sentimentReason: '수요 기대와 가격 둔화 우려가 함께 있어 중립으로 분류됐어요.',
    articleCount: 6,
    pressList: ['아시아경제', '파이낸셜뉴스'],
    publishedAt: '어제',
  },
  {
    id: 301,
    stockCode: '034020',
    title: '해외 원전 프로젝트 우선협상 대상자 선정',
    easySummary:
      '쉽게 말해: 큰 규모의 해외 원전 일감을 따낼 가능성이 한 단계 높아졌어요.',
    sentiment: 'positive',
    sentimentScore: 0.94,
    sentimentReason: '장기 수주 잔고와 향후 매출 확대에 긍정적인 사건이에요.',
    articleCount: 15,
    pressList: ['연합뉴스', '뉴스1', '한국경제'],
    publishedAt: '3시간 전',
  },
  {
    id: 302,
    stockCode: '034020',
    title: '대형 프로젝트 원가 재산정, 단기 비용 반영 가능성',
    easySummary:
      '쉽게 말해: 진행 중인 공사의 예상 비용이 늘어 이번 실적에 부담이 생길 수 있어요.',
    sentiment: 'negative',
    sentimentScore: 0.79,
    sentimentReason: '예상보다 큰 원가는 영업이익을 낮출 수 있어요.',
    articleCount: 4,
    pressList: ['이데일리', '비즈워치'],
    publishedAt: '어제',
  },
  {
    id: 401,
    stockCode: '042660',
    title: '친환경 LNG 운반선 추가 수주 공시',
    easySummary:
      '쉽게 말해: 앞으로 만들 배가 더 늘어 안정적인 매출을 확보했다는 뜻이에요.',
    sentiment: 'positive',
    sentimentScore: 0.91,
    sentimentReason: '수주 잔고 증가가 중장기 실적 가시성을 높여요.',
    articleCount: 9,
    pressList: ['한국경제', '헤럴드경제'],
    publishedAt: '4시간 전',
  },
  {
    id: 402,
    stockCode: '042660',
    title: '후판 가격 협상 장기화, 조선업계 수익성 영향 주시',
    easySummary:
      '쉽게 말해: 배를 만드는 데 쓰는 철판 가격이 아직 정해지지 않아 비용 전망이 불확실해요.',
    sentiment: 'neutral',
    sentimentScore: 0.7,
    sentimentReason: '비용 부담 가능성은 있지만 협상 결과가 확정되지 않았어요.',
    articleCount: 8,
    pressList: ['서울경제', '머니투데이'],
    publishedAt: '어제',
  },
  {
    id: 501,
    stockCode: '005380',
    title: '하이브리드 판매 비중 확대, 북미 판매 호조 지속',
    easySummary:
      '쉽게 말해: 수익성이 좋은 하이브리드차가 북미에서 꾸준히 잘 팔리고 있어요.',
    sentiment: 'positive',
    sentimentScore: 0.9,
    sentimentReason: '판매 구성 개선이 매출과 이익 방어에 도움이 될 수 있어요.',
    articleCount: 11,
    pressList: ['연합뉴스', '오토타임즈', '한국경제'],
    publishedAt: '2시간 전',
  },
  {
    id: 502,
    stockCode: '005380',
    title: '주요 시장 인센티브 확대 여부에 관심',
    easySummary:
      '쉽게 말해: 차를 팔기 위한 할인 비용이 늘어날지 시장이 지켜보고 있어요.',
    sentiment: 'neutral',
    sentimentScore: 0.64,
    sentimentReason: '판매량과 비용에 미칠 영향이 아직 확정되지 않았어요.',
    articleCount: 5,
    pressList: ['매일경제', '뉴스핌'],
    publishedAt: '어제',
  },
]

export const FINANCIALS: Record<string, FinancialItem[]> = {
  '005930': [
    { account: '매출액', display: '79조 1,405억원', yoyPct: 10.1, note: '2026년 1분기' },
    { account: '영업이익', display: '8조 6,052억원', yoyPct: 14.3, note: '2026년 1분기' },
    { account: '당기순이익', display: '6조 7,800억원', yoyPct: 8.7, note: '2026년 1분기' },
  ],
  '000660': [
    { account: '매출액', display: '18조 2,100억원', yoyPct: 21.4, note: '2026년 1분기' },
    { account: '영업이익', display: '7조 2,300억원', yoyPct: 31.8, note: '2026년 1분기' },
    { account: '당기순이익', display: '5조 4,100억원', yoyPct: 26.5, note: '2026년 1분기' },
  ],
  '034020': [
    { account: '매출액', display: '4조 3,820억원', yoyPct: 7.2, note: '2026년 1분기' },
    { account: '영업이익', display: '3,580억원', yoyPct: 12.1, note: '2026년 1분기' },
    { account: '당기순이익', display: '1,940억원', yoyPct: -4.3, note: '2026년 1분기' },
  ],
  '042660': [
    { account: '매출액', display: '3조 1,260억원', yoyPct: 15.8, note: '2026년 1분기' },
    { account: '영업이익', display: '1,430억원', yoyPct: 22.6, note: '2026년 1분기' },
    { account: '당기순이익', display: '980억원', yoyPct: 18.2, note: '2026년 1분기' },
  ],
  '005380': [
    { account: '매출액', display: '44조 4,100억원', yoyPct: 6.4, note: '2026년 1분기' },
    { account: '영업이익', display: '3조 6,900억원', yoyPct: 2.8, note: '2026년 1분기' },
    { account: '당기순이익', display: '3조 2,700억원', yoyPct: 5.1, note: '2026년 1분기' },
  ],
}

export const DISCLOSURES: DisclosureItem[] = STOCKS.flatMap((stock, index) => [
  {
    id: index * 10 + 1,
    stockCode: stock.code,
    type: '정기공시',
    title: '분기보고서 (2026.03)',
    date: '2026.05.15',
    source: 'DART',
  },
  {
    id: index * 10 + 2,
    stockCode: stock.code,
    type: '주요사항',
    title: '단일판매·공급계약 체결',
    date: '2026.05.09',
    source: 'DART',
  },
  {
    id: index * 10 + 3,
    stockCode: stock.code,
    type: '기업정보',
    title: '기업지배구조보고서 공시',
    date: '2026.05.02',
    source: 'DART',
  },
])

export const REPORTS: ReportItem[] = STOCKS.flatMap((stock, index) => [
  {
    id: index * 10 + 1,
    stockCode: stock.code,
    broker: '미래에셋증권',
    title: `${stock.name}, 다음 분기를 보는 세 가지 기준`,
    date: '2026.05.16',
    opinion: '산업 리포트',
  },
  {
    id: index * 10 + 2,
    stockCode: stock.code,
    broker: 'NH투자증권',
    title: '실적 발표 이후 핵심 체크포인트',
    date: '2026.05.10',
    opinion: '기업 분석',
  },
  {
    id: index * 10 + 3,
    stockCode: stock.code,
    broker: '한국투자증권',
    title: '수요 전망과 비용 변수 점검',
    date: '2026.05.03',
    opinion: '산업 분석',
  },
])

export function getStock(stockCode: string) {
  return STOCKS.find((stock) => stock.code === stockCode)
}

export function getStockNews(stockCode: string) {
  return NEWS_CLUSTERS.filter((cluster) => cluster.stockCode === stockCode)
}
