# Upstage models (checked 2026-07-22)

No API key is included. No embedding or text-generation request was made. Generation names were obtained from authenticated `GET https://api.upstage.ai/v1/models`; embedding specifications were checked against Upstage's current official documentation.

## Embedding models currently documented

| Exact API model | Role | Output dimensions | Input limit | Status |
|---|---|---:|---:|---|
| `solar-embedding-2-query` | user/search question | 1,024 | 8,000 tokens | current, full name required |
| `solar-embedding-2-passage` | document/search corpus | 1,024 | 8,000 tokens | current, full name required |
| `embedding-query` → `solar-embedding-1-large-query` | user/search question | 4,096 | 4,000 tokens | deprecated; service ends 2026-08-31 UTC |
| `embedding-passage` → `solar-embedding-1-large-passage` | document/search corpus | 4,096 | 4,000 tokens | deprecated; service ends 2026-08-31 UTC |

Current Embed 2 uses separate query and passage model names in the same retrieval pair. Documents must use the `-passage` model and user questions the `-query` model; vectors from different model generations/dimensions must not be mixed in one index.

The current docs also state a batch request can contain up to 100 texts and up to 204,800 tokens total. Sources: [Upstage Embeddings documentation](https://console.upstage.ai/docs/capabilities/embed), [Upstage model history](https://console.upstage.ai/docs/models/history), and [Upstage API pricing/model status](https://www.upstage.ai/pricing/api).

## Generation models returned for the configured account

Authenticated model catalog HTTP status: 200.

- `solar-mini`
- `solar-mini-250422`
- `solar-pro2`
- `solar-pro2-251215`
- `solar-pro3`
- `solar-pro3-260323`
- `syn-pro`
- `syn-pro-251021`

The application currently pins `solar-pro3-260323` for news same-event classification and factual-summary generation. The RAG generation boundary is still a placeholder and does not select a model in application code.
