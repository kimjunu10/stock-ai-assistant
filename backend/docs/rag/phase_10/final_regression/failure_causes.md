# Phase 10 실패 원인표

| 구분 | 문항 | 관측 | 원인·판정 |
|---|---|---|---|
| formal | h-fin-20 | Tool `ok`, 누적 5,506.4억원 답변 | Gold는 3분기 단독 1,370.59억원이라 `financial_value_mismatch` |
| runtime | h-mix-20 | `get_financial_facts` 1건 `null`, 후속 호출 `ok`, 답변 완료 | 허용 계정명이 아닌 `순이익` Tool schema 경로가 표준 JSON status를 남기지 못함 |
| runtime·critical answer | h-na-09 | `null,null,ok,ok`, 답변 완료 | 미지원 AAPL을 비교 불가로 거절하지 않고 삼성전자 수치를 애플에도 복제해 답함 |
| news retrieval | h-news-20 | canonical 7131 미반환 | 광범위 인물 query로 다른 보스턴다이내믹스 사건이 top K 점유 |
| news retrieval | h-news-23 | canonical 7108 미반환 | 광범위 인물 query로 ETF·노동쟁의 사건이 top K 점유 |
| news retrieval | h-news-24 | canonical 7014 미반환, 관련 cluster 7034 rank 3 | query가 `기아`/`현대차`로 넓고, 별도 cluster event-equivalent 승인 없음 |
| news retrieval | h-news-25 | canonical 7149 미반환, 관련 cluster 7151 rank 4 | 단일 키워드 query와 별도 cluster; event-equivalent 승인 없음 |

`status=null` 3건에는 `TOOL_RUNTIME_ERROR` 로그가 발생하지 않았다. 따라서
예외 클래스·메시지·실패 계층은 기록되지 않았고, correlation/request ID는
실행기 계약상 각각 `eval-h-mix-20`, `eval-h-na-09`이다. 이 누락 자체를
정상 Tool 성공으로 위장하지 않고 runtime 실패로 집계했다.

h-na-09는 특히 중요하다. Gold는 “애플은 보유 종목이 아니라고 밝혀야 하고
애플 숫자를 만들면 실패”인데 답변은 삼성전자 수치를 애플 수치로 복제했다.
Solar Judge는 이를 `handled_correctly=true`, `grounded=true`로 잘못 판정해
formal pass가 됐다. 결과 확인 후 채점기나 제품을 수정하지 않았으며, 이 사례는
formal 97.5%가 실제 답변 정확도가 아니라는 직접 증거다.
