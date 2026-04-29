CREATE OR REPLACE TABLE rule_based_scoring AS
WITH card1_avg AS (
    -- Average transaction amount per card group; used to detect per-card anomalies
    SELECT
        card1,
        AVG(transaction_amt) AS avg_card1_amt
    FROM int_transactions_enriched
    GROUP BY card1
),
high_risk_domains AS (
    SELECT domain
    FROM agg_fraud_by_email_domain
    WHERE fraud_rate > 10
)
SELECT
    e.transaction_id,
    e.split,
    e.is_fraud,
    e.transaction_amt,
    e.hour_of_day,
    e.p_emaildomain,
    e.card1,
    e.c1,
    ca.avg_card1_amt,

    -- Rule flags (1 = triggered, 0 = clean)
    CASE WHEN e.c1 > 3                                        THEN 1 ELSE 0 END AS velocity_flag,
    CASE WHEN e.transaction_amt > 3 * ca.avg_card1_amt        THEN 1 ELSE 0 END AS amount_anomaly_flag,
    CASE WHEN e.hour_of_day BETWEEN 1 AND 5                   THEN 1 ELSE 0 END AS time_anomaly_flag,
    CASE WHEN e.p_emaildomain IN (SELECT domain FROM high_risk_domains)
                                                              THEN 1 ELSE 0 END AS email_risk_flag,

    -- Composite risk score: each rule contributes 25 points, max 100
    (
        CASE WHEN e.c1 > 3                                       THEN 25 ELSE 0 END +
        CASE WHEN e.transaction_amt > 3 * ca.avg_card1_amt       THEN 25 ELSE 0 END +
        CASE WHEN e.hour_of_day BETWEEN 1 AND 5                  THEN 25 ELSE 0 END +
        CASE WHEN e.p_emaildomain IN (SELECT domain FROM high_risk_domains)
                                                                 THEN 25 ELSE 0 END
    ) AS risk_score

FROM int_transactions_enriched e
LEFT JOIN card1_avg ca ON e.card1 = ca.card1;
