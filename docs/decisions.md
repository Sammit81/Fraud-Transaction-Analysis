# Architecture & Design Decisions

## Agent accuracy observation — OpenRouter free-tier model

Using the OpenRouter free-tier model, the investigation agent shows significant inconsistency. The same transaction investigated twice can get opposite assessments (compare runs). More critically, the agent approved two confirmed-fraud transactions at score 75 while declining legitimate ones. This demonstrates why LLM-based investigation is a triage aid, not an automated decision-maker. In production, all high-score transactions should go to human review regardless of agent assessment. A higher-quality model (Claude Haiku/Sonnet) would likely improve consistency but the architectural lesson stands — agents augment analysts, they don't replace them.

The distribution itself is reasonable: 9 high, 5 medium, 6 low across 20 score-75 transactions shows the agent isn't blindly rubber-stamping the rules engine — it's considering context and disagreeing sometimes. The variety of actions (approve, decline, escalate, hold) reflects genuine deliberation. A better model would make the individual decisions more defensible, not more uniform.

## LLM provider strategy

- **Development**: OpenRouter free tier (`nousresearch/hermes-3-llama-3.1-405b:free`). The OpenAI-compatible SDK means swapping providers requires changing only three constants in `python/agent/llm_client.py` (`BASE_URL`, `MODEL`, `API_KEY_ENV`).
- **Showcase**: Claude Haiku 4.5 via Anthropic API. Comparison dimensions to document after the swap: prompt compliance (JSON schema adherence, markdown-fence leakage), reasoning quality (does the model cite specific evidence from the context?), latency per call, and consistency across repeated runs of the same transaction.

## Rule-based scoring design

Four rules, 25 points each, 0–100 composite score. Thresholds derived empirically from the training set:

- **Velocity** (`c1 > 3`): fraud rate doubles at this threshold (2.7% → 6.7%).
- **Amount anomaly** (`transaction_amt > 3× card1 group average`): card-level baseline avoids penalising legitimately high-spending customers.
- **Time anomaly** (`hour_of_day BETWEEN 1 AND 5`): late-night window with elevated fraud prevalence in the dataset.
- **Email domain risk** (domain in `agg_fraud_by_email_domain WHERE fraud_rate > 10%`): three domains qualify — `mail.com` (19.0%), `outlook.es` (13.0%), `aim.com` (12.7%).

Score monotonically predicts fraud rate in training data: 0→2.6%, 25→4.4%, 50→7.6%, 75→21.3%. No transactions hit 100 (all four flags simultaneously) in the current dataset.

## SQL layer design

Three-layer medallion pattern in DuckDB:

- **Staging** (`stg_*`): raw CSV data loaded verbatim, column names lowercased.
- **Intermediate** (`int_transactions_enriched`): LEFT JOIN of transactions + identity (only ~26% of transactions have identity records), plus derived time and amount features.
- **Marts** (`fct_fraud_analysis`, `agg_fraud_by_email_domain`): train-split-only views shaped for Power BI consumption.
- **Scoring** (`rule_based_scoring`): scores all splits so the same rules can be applied to the test set.

DuckDB was chosen over a hosted warehouse for this project because the full dataset (590k train + 507k test rows) fits comfortably in memory, there's no multi-user concurrency requirement, and the file-based database makes the repo self-contained for portfolio review.
