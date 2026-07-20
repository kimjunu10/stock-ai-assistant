# Moa AI Frontend

뉴스·공시·리포트·재무 정보를 초보 투자자가 쉽게 이해하도록 정리하는 React UI 프로토타입입니다. 거래·주문·계좌 연결 기능은 포함하지 않습니다.

## 기술 구성

- React 19 + TypeScript + Vite
- Tailwind CSS 4 (`@tailwindcss/vite`)
- TradingView Advanced Chart Widget
- 별도 라우터 패키지 없이 History API 기반 프로토타입 라우팅

## 실행

```bash
npm install
npm run dev
```

기본 주소는 `http://localhost:5173`입니다.

```bash
npm run lint
npm run build
npm run preview
```

## 화면 경로

- `/` — 서비스 홈, 5개 분석 종목, 주요 뉴스 브리핑
- `/stocks` — 5개 종목 목록
- `/stocks/:stock_code` — 종목 헤더, TradingView 차트, 주요 뉴스, 재무, 공시, 리포트
- `/news` — 종목·호재/악재/중립 필터가 있는 클러스터 뉴스 피드
- `/ask` — 종목 선택과 출처 칩을 포함한 GPT형 전역 질문 화면

## TradingView 차트

`TradingViewChart`는 종목 코드에 맞춰 아래 심볼을 사용합니다.

| 종목 코드 | TradingView 심볼 |
| --- | --- |
| 005930 | KRX:005930 |
| 000660 | KRX:000660 |
| 034020 | KRX:034020 |
| 042660 | KRX:042660 |
| 005380 | KRX:005380 |

공통 설정은 1일봉(`D`), 최근 6개월(`6M`), 캔들, 거래량 표시, 한국어(`ko`), `autosize`, 심볼 변경 금지입니다. 앱 테마가 바뀌면 위젯도 안전하게 다시 생성됩니다. 로딩·스크립트 실패·재시도·언마운트 정리를 구현했고 TradingView 출처 링크를 유지합니다.

TradingView의 시장 데이터 배포 정책에 따라 KRX 심볼은 임베드 iframe 안에서 `This symbol is only available on TradingView` 안내가 표시될 수 있습니다. 이 경우에도 요청된 KRX 심볼과 출처 링크는 유지되며, 심볼을 임의의 다른 시장 종목으로 대체하지 않습니다.

## 데이터 연결 범위

현재 카드와 가격 숫자는 레이아웃 검증용 샘플 데이터입니다. TradingView 데이터는 AI 답변이나 백엔드 계산에 사용하지 않습니다. 뉴스 이후 수익률과 뉴스 마커는 향후 별도 `prices` API/DB 연동 후 구현합니다.
