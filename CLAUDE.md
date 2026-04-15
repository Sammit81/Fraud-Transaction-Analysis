# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for dependency management.

```bash
uv sync                          # install dependencies
uv run main.py                   # run main entry point
uv run python/agents/investigate.py   # smoke test the agent pipeline with a fake transaction
```

## Architecture

The project is a fraud investigation agent pipeline that:
1. Reads flagged transactions from a DuckDB database (`data/duckdb/fraud.duckdb`)
2. Enriches each transaction with customer context (30-day history, recent transactions, similar patterns)
3. Sends the context to an LLM via `python/agents/investigate.py:investigate_transaction()`
4. Parses and validates the structured JSON response into an `InvestigationResult` dataclass
5. Writes results to the `case_notes` table for downstream Power BI consumption

### Key files

- `python/agents/llm_client.py` — provider-agnostic OpenAI SDK wrapper pointed at OpenRouter. To swap LLM providers, change only `BASE_URL`, `MODEL`, and `API_KEY_ENV` at the top of this file.
- `python/agents/prompts.py` — system prompt and investigation template. Versioned intentionally; old versions should be preserved in git history.
- `python/agents/investigate.py` — agent logic: prompt building, LLM call with retry on parse failure, JSON extraction/validation, and DB write.

### LLM response contract

The LLM must return a JSON object with these fields: `risk_assessment` (`low|medium|high|critical`), `likely_pattern`, `confidence` (float 0–1), `reasoning`, `recommended_action`, and `case_note`. `extract_json()` in `investigate.py` strips markdown fences before parsing, since open models often add them despite instructions. Failed parses retry up to `max_retries` (default 2) times before giving up.

### LLM provider strategy

- **Development**: OpenRouter free tier with `nousresearch/hermes-3-llama-3.1-405b:free`. The OpenAI-compatible SDK means the provider swaps by changing three constants in `python/agents/llm_client.py` (`BASE_URL`, `MODEL`, `API_KEY_ENV`).
- **Final showcase**: Claude Haiku 4.5 via Anthropic API for output quality. Document the comparison (prompt behaviour, output quality, latency) in `docs/decisions.md`.

### Environment

Requires `OPENROUTER_API_KEY` in `.env` (loaded via `python-dotenv`). For Anthropic API runs, add `ANTHROPIC_API_KEY`.
