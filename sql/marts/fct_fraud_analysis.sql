CREATE OR REPLACE TABLE fct_fraud_analysis AS
SELECT
    transaction_id,
    is_fraud,
    transaction_amt,
    amount_bucket,
    hour_of_day,
    day_of_week,
    product_cd,
    card4,
    card6,
    p_emaildomain,
    device_type,
    device_info,
    id_12,
    id_13,
    id_14,
    id_15
FROM int_transactions_enriched
WHERE split = 'train';
