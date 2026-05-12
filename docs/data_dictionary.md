# Data Dictionary

All tables live in `data/duckdb/fraud.duckdb`. Source dataset: [IEEE-CIS Fraud Detection](https://www.kaggle.com/c/ieee-fraud-detection).

---

## Staging

### `stg_transactions`
Raw transaction records, train and test CSVs unioned. `is_fraud` is NULL for test rows.

| Column | Type | Description |
|--------|------|-------------|
| `split` | VARCHAR | `'train'` or `'test'` |
| `transaction_id` | INTEGER | Primary key |
| `is_fraud` | BOOLEAN | Ground truth label. NULL for test split |
| `transaction_dt` | INTEGER | Seconds elapsed since a fixed reference point (not a real timestamp) |
| `transaction_amt` | FLOAT | Transaction amount in USD |
| `product_cd` | VARCHAR | Product category: `W`=wireless, `H`=home, `C`=computer, `S`=services, `R`=retail |
| `card1` | INTEGER | Card issuer grouping (anonymised) — used as the baseline for amount anomaly scoring |
| `card2` | INTEGER | Card attribute (anonymised) |
| `card3` | INTEGER | Card attribute (anonymised) |
| `card4` | VARCHAR | Card network: `visa`, `mastercard`, `discover`, `american express` |
| `card5` | INTEGER | Card attribute (anonymised) |
| `card6` | VARCHAR | Card type: `credit` or `debit` |
| `addr1` | FLOAT | Billing address: postcode area |
| `addr2` | FLOAT | Billing address: country code |
| `dist1` | FLOAT | Distance between billing and mailing zip codes |
| `dist2` | FLOAT | Distance between billing and identity zip codes |
| `p_emaildomain` | VARCHAR | Purchaser email domain (lowercased) |
| `r_emaildomain` | VARCHAR | Recipient email domain (lowercased) |
| `c1`–`c14` | FLOAT | Counting features engineered by Vesta. `c1` = number of payment cards associated with the address — used as the velocity signal |
| `d1`–`d15` | FLOAT | Timedelta features (days since previous events) |
| `m1`–`m9` | VARCHAR | Match features (e.g., whether billing address matches mailing address) |
| `v1`–`v339` | FLOAT | Anonymised Vesta-engineered features. Not used in this project's scoring layer |

**Null rates (selected columns):**
| Column | Null % |
|--------|--------|
| `dist1` | ~59% |
| `dist2` | ~94% |
| `p_emaildomain` | ~24% |
| `r_emaildomain` | ~48% |
| `d2`, `d7`–`d9` | >60% |

---

### `stg_identity`
Identity records. Only ~26% of training transactions have a matching row.

| Column | Type | Description |
|--------|------|-------------|
| `transaction_id` | INTEGER | Foreign key to `stg_transactions` |
| `split` | VARCHAR | `'train'` or `'test'` |
| `id_01`–`id_11` | FLOAT | Numeric identity attributes (anonymised) |
| `id_12`–`id_38` | VARCHAR | Categorical identity attributes (anonymised). `id_30`=OS, `id_31`=browser |
| `device_type` | VARCHAR | `'desktop'` or `'mobile'` |
| `device_info` | VARCHAR | Device model/OS string (free text, high cardinality) |

---

## Intermediate

### `int_transactions_enriched`
LEFT JOIN of `stg_transactions` + `stg_identity`, with derived features. Contains all splits.

| Column | Source | Description |
|--------|--------|-------------|
| *(all stg_transactions columns)* | staging | Passed through unchanged |
| *(selected stg_identity columns)* | staging | `id_12`–`id_20`, `id_30`, `id_31`, `id_35`–`id_38`, `device_type`, `device_info`. NULL where no identity record exists |
| `hour_of_day` | derived | `(transaction_dt % 86400) / 3600` — 0–23. Used by time anomaly rule (flags 1–5 AM) |
| `day_of_week` | derived | `(transaction_dt % 604800) / 86400` — 0–6 |
| `amount_bucket` | derived | Categorical band: `under_10`, `10_to_50`, `50_to_200`, `200_to_500`, `over_500` |

---

## Marts

### `fct_fraud_analysis`
Training split only. Subset of `int_transactions_enriched` columns shaped for Tableau.

| Column | Description |
|--------|-------------|
| `transaction_id` | PK |
| `is_fraud` | Ground truth label |
| `transaction_amt` | Amount |
| `amount_bucket` | Derived band |
| `hour_of_day` | Derived hour |
| `day_of_week` | Derived day |
| `product_cd` | Product category |
| `card4` | Card network |
| `card6` | Credit / debit |
| `p_emaildomain` | Purchaser email domain |
| `device_type` | Desktop / mobile |
| `device_info` | Device string |
| `id_12`–`id_15` | Identity attributes |

---

### `agg_fraud_by_email_domain`
Fraud rate per purchaser email domain. Only domains with ≥ 100 transactions are included to avoid unreliable small-sample rates. Used by the scoring layer to identify high-risk domains (threshold: fraud rate > 10%).

| Column | Description |
|--------|-------------|
| `domain` | Purchaser email domain |
| `total_transactions` | Row count |
| `fraud_count` | Fraudulent transactions |
| `fraud_rate` | `fraud_count / total_transactions × 100` |
| `avg_amount` | Average transaction amount across all transactions for this domain |
| `avg_fraud_amount` | Average transaction amount for fraudulent transactions only |

**Domains above the 10% threshold (used in scoring):**

| Domain | Fraud rate |
|--------|-----------|
| `mail.com` | 19.0% |
| `outlook.es` | 13.0% |
| `aim.com` | 12.7% |

---

## Scoring

### `rule_based_scoring`
Applies four binary rules to all splits. Each rule contributes 25 points; composite score ranges 0–100. No transactions in the dataset hit 100 (all four rules simultaneously).

| Column | Description |
|--------|-------------|
| `transaction_id` | PK |
| `split` | `'train'` or `'test'` |
| `is_fraud` | Ground truth (NULL for test) |
| `transaction_amt` | Amount |
| `hour_of_day` | Derived hour |
| `p_emaildomain` | Purchaser email domain |
| `card1` | Card group |
| `c1` | Velocity count |
| `avg_card1_amt` | Average transaction amount for this `card1` group |
| `velocity_flag` | 1 if `c1 > 3` |
| `amount_anomaly_flag` | 1 if `transaction_amt > 3 × avg_card1_amt` |
| `time_anomaly_flag` | 1 if `hour_of_day BETWEEN 1 AND 5` |
| `email_risk_flag` | 1 if `p_emaildomain` has fraud rate > 10% in training data |
| `risk_score` | Sum of flags × 25. Values: 0, 25, 50, 75 |

**Scoring validation (training split):**

| Score | Fraud rate |
|-------|-----------|
| 0 | 2.6% |
| 25 | 4.4% |
| 50 | 7.6% |
| 75 | 21.3% |

---

## Agent output

### `case_notes`
Written by `python/agent/batch_investigate.py` after LLM investigation.

| Column | Description |
|--------|-------------|
| `transaction_id` | FK to `rule_based_scoring` |
| `risk_assessment` | `low`, `medium`, `high`, or `critical` — LLM's assessment independent of the rule score |
| `likely_pattern` | One of: `card_testing`, `account_takeover`, `synthetic_identity`, `friendly_fraud`, `merchant_fraud`, `legitimate`, `insufficient_evidence` |
| `confidence` | Float 0–1. LLM self-reported confidence in its assessment |
| `reasoning` | 2–4 sentences citing specific evidence from the transaction context |
| `recommended_action` | `approve`, `decline`, `escalate_to_senior`, `contact_customer`, `hold_for_review` |
| `case_note` | 3–5 sentence professional case note for the investigation record |
| `raw_response` | Full LLM response string, preserved for audit and debugging |
