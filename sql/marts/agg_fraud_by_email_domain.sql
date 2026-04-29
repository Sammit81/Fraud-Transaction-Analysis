CREATE OR REPLACE TABLE agg_fraud_by_email_domain AS
SELECT
    p_emaildomain                                                                      AS domain,
    COUNT(*)                                                                           AS total_transactions,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)                                         AS fraud_count,
    ROUND(100.0 * SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END) / COUNT(*), 4)            AS fraud_rate,
    ROUND(AVG(transaction_amt), 2)                                                    AS avg_amount,
    ROUND(AVG(CASE WHEN is_fraud THEN transaction_amt END), 2)                        AS avg_fraud_amount
FROM fct_fraud_analysis
GROUP BY p_emaildomain
HAVING COUNT(*) >= 100
ORDER BY fraud_rate DESC;
