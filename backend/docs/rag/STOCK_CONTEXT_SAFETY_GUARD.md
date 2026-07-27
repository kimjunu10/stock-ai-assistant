# Stock context safety guard

## Scope

This change prevents a single-stock screen request from being answered with data
belonging to a different company. It does not change prompts, retriever behavior,
evaluation Gold, or graders.

## Confirmed root cause

`AgentQaService.answer()` passed the screen-selected `stock_code` into the Agent
runtime without validating company names explicitly present in the question.
Separately, `_resolve_stock_code()` accepted any six-digit Tool argument and
replaced every non-six-digit argument with the screen-selected code.

Consequently, a model Tool argument such as `AAPL` was silently converted to
`005930`. The Tool then returned Samsung Electronics data even though the user
had asked about Apple, leaving the model able to relabel the grounded Samsung
numbers as Apple numbers.

## Safety flow

1. The UI-selected stock is the authoritative context.
2. Before event resolution, Agent invocation, or Tool invocation, the service
   detects supported company mentions using the existing
   `STOCK_MENTION_RULES` and `SUPPORTED_STOCK_CODES`.
3. No company mention and the same supported company continue normally.
4. A different supported company returns `STOCK_CONTEXT_MISMATCH`.
5. An unsupported company returns `UNSUPPORTED_STOCK`.
6. Multiple companies return `MULTI_STOCK_NOT_SUPPORTED`.
7. Runtime Tool arguments no longer fall back when they identify another or an
   unsupported stock. Such attempts are recorded against the correlation ID.
8. Before constructing the final answer, the selected code, runtime code,
   explicit Tool-call code, Tool payload, source `stock_code`, and deterministic
   source keys are compared. Any mismatch returns a safe response with no
   sources, visualizations, or broker cards.
9. The regular and SSE APIs expose the same error code. The frontend clears any
   previously received cards/sources, and a supported-stock mismatch focuses and
   highlights the stock selector without changing it automatically.

## Hardcoding check

The product implementation contains no holdout ID, cluster ID, news title,
question phrase, or Apple-specific exception. Supported names/codes come from
the existing backend stock sources of truth. Unsupported companies are detected
by general financial-question grammar rather than a company-name blocklist.

## Pre-deployment verification

- Targeted backend safety/API/runtime tests: 53 passed.
- Backend unit and Agent regression tests: 576 passed.
- Backend lint: `ruff check .` passed.
- Backend format: `ruff format --check .` passed.
- Frontend tests: 20 passed.
- Frontend lint: passed.
- Frontend production build: passed.

The 40-question holdout and the 120-question development set were not run.
