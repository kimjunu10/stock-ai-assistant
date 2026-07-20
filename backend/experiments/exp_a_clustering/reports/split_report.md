# 데이터 분할 리포트 (group-aware stock-balanced split)
> reference set: AI-reviewed reference set (human gold set 아님)
> seed=42, 목표 development 60% / validation 20% / test 20%

## 누출 검사 (0이어야 함)
- article_id split 중복: **0**
- gold_event_id split 중복: **0**
- split_unit_id split 중복: **0**

## split별 행수/비율
| split | 행수 | 비율 | eligible행 |
|---|---:|---:|---:|
| development | 676 | 61.5% | 670 |
| validation | 212 | 19.3% | 207 |
| test | 212 | 19.3% | 210 |

## 종목별 split 행수
| 종목 | development | validation | test |
|---|---:|---:|---:|
| 005930 | 136 | 37 | 47 |
| 000660 | 144 | 43 | 33 |
| 034020 | 132 | 44 | 44 |
| 042660 | 130 | 43 | 47 |
| 005380 | 134 | 45 | 41 |

## split별 사건/단독사건/날짜범위
| split | 사건수 | 단독사건 | 날짜 min | 날짜 max |
|---|---:|---:|---|---|
| development | 65 | 25 | 2026-07-01 | 2026-07-20 |
| validation | 68 | 42 | 2026-07-01 | 2026-07-20 |
| test | 74 | 42 | 2026-07-01 | 2026-07-20 |
