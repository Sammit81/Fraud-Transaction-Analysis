CREATE OR REPLACE TABLE int_transactions_enriched AS
SELECT
    t.split,
    t.transaction_id,
    t.is_fraud,
    t.transaction_dt,
    t.transaction_amt,
    t.product_cd,
    t.card1,
    t.card2,
    t.card3,
    t.card4,
    t.card5,
    t.card6,
    t.addr1,
    t.addr2,
    t.dist1,
    t.dist2,
    t.p_emaildomain,
    t.r_emaildomain,
    t.c1,
    t.c2,
    t.c3,
    t.c4,
    t.c5,
    t.c6,
    t.c7,
    t.c8,
    t.c9,
    t.c10,
    t.c11,
    t.c12,
    t.c13,
    t.c14,
    -- Identity columns (NULL when no identity record exists for the transaction)
    i.id_12,
    i.id_13,
    i.id_14,
    i.id_15,
    i.id_16,
    i.id_17,
    i.id_18,
    i.id_19,
    i.id_20,
    i.id_30,
    i.id_31,
    i.id_35,
    i.id_36,
    i.id_37,
    i.id_38,
    i.device_type,
    i.device_info,
    -- Derived time features: transaction_dt is seconds since a reference point
    CAST((t.transaction_dt % 86400) / 3600 AS INTEGER)   AS hour_of_day,
    CAST((t.transaction_dt % 604800) / 86400 AS INTEGER) AS day_of_week,
    -- Amount bucket for categorical grouping in reports
    CASE
        WHEN t.transaction_amt < 10    THEN 'under_10'
        WHEN t.transaction_amt < 50    THEN '10_to_50'
        WHEN t.transaction_amt < 200   THEN '50_to_200'
        WHEN t.transaction_amt < 500   THEN '200_to_500'
        ELSE                                'over_500'
    END AS amount_bucket
FROM stg_transactions t
LEFT JOIN stg_identity i
    ON t.transaction_id = i.transaction_id;
