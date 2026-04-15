"""Fraud investigation agent. Reads flagged transactions from DuckDB,
runs them through the LLM, writes structured case notes back."""
import json
import re
from dataclasses import dataclass
from typing import Optional

import duckdb

from .llm_client import call_llm
from .prompts import SYSTEM_PROMPT, INVESTIGATION_TEMPLATE


DB_PATH = "data/duckdb/fraud.duckdb"


@dataclass
class InvestigationResult:
    transaction_id: str
    risk_assessment: str
    likely_pattern: str
    confidence: float
    reasoning: str
    recommended_action: str
    case_note: str
    raw_response: str  # keep for debugging and audit


def extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a string. Handles markdown
    fences and preamble that some open models add despite instructions."""
    # Strip common markdown wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)

    # Find the first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def build_user_prompt(transaction_context: dict) -> str:
    """Fill the investigation template with context pulled from DuckDB."""
    return INVESTIGATION_TEMPLATE.format(**transaction_context)


def investigate_transaction(
    transaction_context: dict,
    transaction_id: str,
    max_retries: int = 2,
) -> Optional[InvestigationResult]:
    """Run one transaction through the agent. Retries on parse failure."""
    user_prompt = build_user_prompt(transaction_context)

    for attempt in range(max_retries + 1):
        raw = call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = extract_json(raw)

        if parsed and _validate_schema(parsed):
            return InvestigationResult(
                transaction_id=transaction_id,
                risk_assessment=parsed["risk_assessment"],
                likely_pattern=parsed["likely_pattern"],
                confidence=float(parsed["confidence"]),
                reasoning=parsed["reasoning"],
                recommended_action=parsed["recommended_action"],
                case_note=parsed["case_note"],
                raw_response=raw,
            )
        print(f"Parse failure on attempt {attempt + 1} for {transaction_id}")

    print(f"Giving up on {transaction_id} after {max_retries + 1} attempts")
    return None


def _validate_schema(parsed: dict) -> bool:
    """Cheap schema check. Catches the most common model errors."""
    required = {
        "risk_assessment", "likely_pattern", "confidence",
        "reasoning", "recommended_action", "case_note",
    }
    if not required.issubset(parsed.keys()):
        return False
    if parsed["risk_assessment"] not in {"low", "medium", "high", "critical"}:
        return False
    if not 0.0 <= float(parsed["confidence"]) <= 1.0:
        return False
    return True


def write_result_to_db(result: InvestigationResult) -> None:
    """Persist the investigation result for Power BI to consume."""
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS case_notes (
            transaction_id VARCHAR PRIMARY KEY,
            risk_assessment VARCHAR,
            likely_pattern VARCHAR,
            confidence DOUBLE,
            reasoning VARCHAR,
            recommended_action VARCHAR,
            case_note VARCHAR,
            raw_response VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        INSERT OR REPLACE INTO case_notes
        (transaction_id, risk_assessment, likely_pattern, confidence,
         reasoning, recommended_action, case_note, raw_response)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result.transaction_id, result.risk_assessment, result.likely_pattern,
        result.confidence, result.reasoning, result.recommended_action,
        result.case_note, result.raw_response,
    ))
    con.close()


if __name__ == "__main__":
    # Smoke test with a fake transaction so you can verify the pipeline
    # works before wiring it to real DuckDB queries.
    fake_context = {
        "transaction_details": "ID: TXN_TEST_001 | Amount: $4,250 | Merchant: Online Electronics Retailer | Time: 03:47 UTC | Card present: No",
        "triggered_rules": "- Velocity: 8 transactions in last 30 minutes\n- Amount: 12x customer 30-day average\n- Time: outside typical hours (customer usually transacts 09:00-22:00)",
        "txn_count_30d": 47,
        "avg_amount_30d": "$87.30",
        "typical_categories": "Groceries, Restaurants, Petrol",
        "typical_hours": "09:00-22:00",
        "devices": "iPhone (primary), MacBook (occasional)",
        "countries": "Ireland (100%)",
        "recent_transactions": "Last 10 txns avg $94, all in Ireland, all on known devices, all 09:00-22:00",
        "similar_patterns": "Pattern matches known card-testing followed by high-value purchase scheme seen in Q2 cases",
    }

    result = investigate_transaction(fake_context, "TXN_TEST_001")
    if result:
        print(json.dumps(result.__dict__, indent=2))
        write_result_to_db(result)
        print("Written to case_notes table")
    else:
        print("Investigation failed")