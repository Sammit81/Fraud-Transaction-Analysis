"""Batch fraud investigation against real DuckDB data.

Pulls the top --limit transactions by risk score from rule_based_scoring,
builds LLM context from DuckDB, runs the agent, and writes results to case_notes.
"""
import argparse
import time
from collections import Counter

import duckdb

from .investigate import investigate_transaction, write_result_to_db

DB_PATH = "data/duckdb/fraud.duckdb"
SLEEP_BETWEEN_CALLS = 3  # seconds — OpenRouter free-tier rate limit


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_candidates(con: duckdb.DuckDBPyConnection, limit: int) -> list[dict]:
    """Top N transactions by risk_score, with display columns joined in."""
    rows = con.execute("""
        SELECT
            r.transaction_id,
            r.risk_score,
            r.velocity_flag,
            r.amount_anomaly_flag,
            r.time_anomaly_flag,
            r.email_risk_flag,
            r.transaction_amt,
            r.hour_of_day,
            r.p_emaildomain,
            r.card1,
            r.c1,
            r.avg_card1_amt,
            r.is_fraud,
            e.product_cd,
            e.card4,
            e.card6,
            e.r_emaildomain,
            e.device_type,
            e.device_info
        FROM rule_based_scoring r
        JOIN int_transactions_enriched e ON r.transaction_id = e.transaction_id
        WHERE r.split = 'train'
          AND r.is_fraud IS NOT NULL
        ORDER BY r.risk_score DESC, r.transaction_amt DESC
        LIMIT ?
    """, [limit]).fetchall()

    cols = [
        "transaction_id", "risk_score", "velocity_flag", "amount_anomaly_flag",
        "time_anomaly_flag", "email_risk_flag", "transaction_amt", "hour_of_day",
        "p_emaildomain", "card1", "c1", "avg_card1_amt", "is_fraud",
        "product_cd", "card4", "card6", "r_emaildomain", "device_type", "device_info",
    ]
    return [dict(zip(cols, row)) for row in rows]


def fetch_customer_context(con: duckdb.DuckDBPyConnection, card1: int) -> dict:
    """Aggregate stats for all training transactions on the same card."""
    row = con.execute("""
        SELECT
            COUNT(*)                           AS txn_count,
            ROUND(AVG(transaction_amt), 2)     AS avg_amount,
            ROUND(MIN(transaction_amt), 2)     AS min_amount,
            ROUND(MAX(transaction_amt), 2)     AS max_amount,
            MIN(hour_of_day)                   AS min_hour,
            MAX(hour_of_day)                   AS max_hour,
            mode(product_cd)                   AS typical_product
        FROM int_transactions_enriched
        WHERE card1 = ? AND split = 'train'
    """, [card1]).fetchone()

    return {
        "txn_count":       row[0],
        "avg_amount":      row[1],
        "min_amount":      row[2],
        "max_amount":      row[3],
        "min_hour":        row[4],
        "max_hour":        row[5],
        "typical_product": row[6],
    }


def fetch_recent_transactions(
    con: duckdb.DuckDBPyConnection, card1: int, exclude_id: int
) -> list[dict]:
    """Last 10 transactions on the same card, most recent first.

    The current transaction is excluded so the LLM isn't shown the thing it's
    investigating as part of the history.
    """
    rows = con.execute("""
        SELECT
            transaction_id,
            ROUND(transaction_amt, 2) AS amt,
            product_cd,
            hour_of_day,
            amount_bucket,
            is_fraud
        FROM int_transactions_enriched
        WHERE card1 = ?
          AND transaction_id != ?
          AND split = 'train'
        ORDER BY transaction_dt DESC
        LIMIT 10
    """, [card1, exclude_id]).fetchall()

    cols = ["transaction_id", "amt", "product_cd", "hour_of_day", "amount_bucket", "is_fraud"]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------

def _format_triggered_rules(txn: dict) -> str:
    rules = []
    if txn["velocity_flag"]:
        rules.append(
            f"- Velocity: c1={txn['c1']:.0f} (threshold >3) — elevated transaction count on this card"
        )
    if txn["amount_anomaly_flag"] and txn["avg_card1_amt"]:
        ratio = txn["transaction_amt"] / txn["avg_card1_amt"]
        rules.append(
            f"- Amount anomaly: ${txn['transaction_amt']:.2f} is {ratio:.1f}x "
            f"the card's average (${txn['avg_card1_amt']:.2f})"
        )
    if txn["time_anomaly_flag"]:
        rules.append(
            f"- Time anomaly: transaction at {txn['hour_of_day']}:00 (1am–5am suspicious window)"
        )
    if txn["email_risk_flag"]:
        rules.append(
            f"- High-risk email domain: {txn['p_emaildomain']} (>10% fraud rate in training data)"
        )
    return "\n".join(rules) if rules else "No rules triggered"


def _format_recent_transactions(recent: list[dict]) -> str:
    if not recent:
        return "No prior transactions on this card in the dataset"
    lines = []
    for r in recent:
        fraud_tag = " [FRAUD]" if r["is_fraud"] else ""
        lines.append(
            f"  TXN#{r['transaction_id']} | ${r['amt']:.2f} | "
            f"{r['product_cd'] or 'N/A'} | {r['hour_of_day']}:00 | "
            f"{r['amount_bucket']}{fraud_tag}"
        )
    return "\n".join(lines)


def build_context(txn: dict, customer: dict, recent: list[dict]) -> dict:
    """Map query results to the fields expected by INVESTIGATION_TEMPLATE."""
    flags_fired = sum([
        txn["velocity_flag"], txn["amount_anomaly_flag"],
        txn["time_anomaly_flag"], txn["email_risk_flag"],
    ])

    device_parts = [p for p in [txn.get("device_type"), txn.get("device_info")] if p]
    device_str = " / ".join(device_parts) if device_parts else "not available"

    return {
        "transaction_details": (
            f"ID: {txn['transaction_id']} | "
            f"Amount: ${txn['transaction_amt']:.2f} | "
            f"Product: {txn['product_cd'] or 'N/A'} | "
            f"Card network: {txn['card4'] or 'N/A'} ({txn['card6'] or 'N/A'}) | "
            f"Purchaser email domain: {txn['p_emaildomain'] or 'N/A'} | "
            f"Recipient email domain: {txn['r_emaildomain'] or 'N/A'} | "
            f"Hour: {txn['hour_of_day']}:00 | "
            f"Risk score: {txn['risk_score']}/100 | "
            f"Known fraud label: {'yes' if txn['is_fraud'] else 'no'}"
        ),
        "triggered_rules": _format_triggered_rules(txn),
        "txn_count_30d": customer["txn_count"],
        "avg_amount_30d": f"${customer['avg_amount']:.2f}",
        "typical_categories": customer["typical_product"] or "N/A",
        "typical_hours": f"{customer['min_hour']}:00–{customer['max_hour']}:00",
        "devices": device_str,
        "countries": "not available in this dataset",
        "recent_transactions": _format_recent_transactions(recent),
        "similar_patterns": (
            f"Risk score {txn['risk_score']}/100 — {flags_fired} of 4 rules fired. "
            f"Card group has {customer['txn_count']} total training transactions, "
            f"amount range ${customer['min_amount']:.2f}–${customer['max_amount']:.2f} "
            f"(avg ${customer['avg_amount']:.2f})."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch fraud investigation using the LLM agent."
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Number of transactions to investigate (default: 5)",
    )
    args = parser.parse_args()

    # Fetch all data with a read-only connection before the LLM loop.
    # write_result_to_db opens its own write connection — keeping a second
    # connection open during writes would conflict in DuckDB.
    print(f"Fetching top {args.limit} transactions by risk score...")
    con = duckdb.connect(DB_PATH, read_only=True)
    candidates = fetch_candidates(con, args.limit)

    enriched = []
    for txn in candidates:
        customer = fetch_customer_context(con, txn["card1"])
        recent = fetch_recent_transactions(con, txn["card1"], txn["transaction_id"])
        enriched.append((txn, customer, recent))
    con.close()

    print(f"Loaded {len(enriched)} transactions. Starting LLM investigations...\n")

    results = []
    failed = []

    for i, (txn, customer, recent) in enumerate(enriched, 1):
        tid = str(txn["transaction_id"])
        print(
            f"[{i}/{len(enriched)}] TXN#{tid} | "
            f"score={txn['risk_score']} | "
            f"${txn['transaction_amt']:.2f} | "
            f"fraud={txn['is_fraud']}"
        )

        context = build_context(txn, customer, recent)
        result = investigate_transaction(context, tid)

        if result:
            write_result_to_db(result)
            results.append(result)
            print(
                f"  → {result.risk_assessment} | "
                f"{result.recommended_action} | "
                f"confidence={result.confidence:.2f}"
            )
        else:
            failed.append(tid)
            print("  → FAILED (parse error after retries)")

        if i < len(enriched):
            time.sleep(SLEEP_BETWEEN_CALLS)

    # Summary
    print(f"\n{'=' * 60}")
    print("BATCH COMPLETE")
    print(f"  Investigated : {len(enriched)}")
    print(f"  Succeeded    : {len(results)}")
    print(f"  Failed       : {len(failed)}")
    if failed:
        print(f"  Failed IDs   : {', '.join(failed)}")

    if results:
        risk_counts = Counter(r.risk_assessment for r in results)
        action_counts = Counter(r.recommended_action for r in results)

        print("\n  Risk assessments:")
        for label, count in sorted(risk_counts.items()):
            print(f"    {label:<20} {count}")

        print("\n  Recommended actions:")
        for label, count in sorted(action_counts.items()):
            print(f"    {label:<20} {count}")


if __name__ == "__main__":
    main()
