"""
Load IEEE-CIS fraud CSVs into DuckDB staging tables.

Tables written:
  stg_transactions  — train + test unioned, split column added, is_fraud NULL for test
  stg_identity      — train + test unioned, id-NN column names normalized to id_NN

Run from project root:
  uv run python/load_data.py
"""

import csv
import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "duckdb" / "fraud.duckdb"

# Columns whose names need more than a simple lowercase: CamelCase → snake_case
RENAME_MAP = {
    "TransactionID": "transaction_id",
    "TransactionDT": "transaction_dt",
    "TransactionAmt": "transaction_amt",
    "ProductCD": "product_cd",
    "isFraud": "is_fraud",
    "DeviceType": "device_type",
    "DeviceInfo": "device_info",
}

# Applied inline as LOWER(col)
EMAIL_COLS = {"P_emaildomain", "R_emaildomain"}

# Stored as "404.0" floats in CSV; cast to integer
CARD_INT_COLS = {"card2", "card3", "card5"}


def get_headers(path: Path) -> list[str]:
    with open(path, newline="") as f:
        return next(csv.reader(f))


def normalize_col(name: str) -> str:
    """Original CSV column name → target snake_case name in DuckDB."""
    if name in RENAME_MAP:
        return RENAME_MAP[name]
    return name.lower().replace("-", "_")


def build_txn_select(headers: list[str], split: str, has_fraud: bool) -> str:
    """
    Build a SQL SELECT clause for one transaction CSV.
    Adds the split literal and handles is_fraud, email lowercasing, card int casts.
    """
    parts = [f"'{split}' AS split"]

    if has_fraud:
        parts.append("isFraud::BOOLEAN AS is_fraud")
    else:
        parts.append("NULL::BOOLEAN AS is_fraud")

    for col in headers:
        if col == "isFraud":
            continue  # already handled above

        snake = normalize_col(col)

        if col in EMAIL_COLS:
            parts.append(f'LOWER("{col}") AS {snake}')
        elif col in CARD_INT_COLS:
            # TRY_CAST: unexpected values become NULL rather than aborting
            parts.append(f'TRY_CAST("{col}" AS INTEGER) AS {snake}')
        elif snake != col:
            parts.append(f'"{col}" AS {snake}')
        else:
            parts.append(col)

    return ",\n    ".join(parts)


def build_identity_select(headers: list[str], split: str) -> str:
    """
    Build a SQL SELECT clause for one identity CSV.
    Normalizes id-NN (test hyphen convention) → id_NN and renames DeviceType/Info.
    """
    parts = [f"'{split}' AS split"]
    for col in headers:
        snake = normalize_col(col)
        if snake != col:
            parts.append(f'"{col}" AS {snake}')
        else:
            parts.append(col)
    return ",\n    ".join(parts)


def csv_path(name: str) -> str:
    """Return a quoted POSIX path string safe for embedding in DuckDB SQL."""
    return str((RAW_DIR / name).as_posix())


def load_transactions(con: duckdb.DuckDBPyConnection) -> None:
    train_headers = get_headers(RAW_DIR / "train_transaction.csv")
    test_headers = get_headers(RAW_DIR / "test_transaction.csv")

    train_sel = build_txn_select(train_headers, "train", has_fraud=True)
    test_sel = build_txn_select(test_headers, "test", has_fraud=False)

    print("Loading train_transaction.csv → stg_transactions …")
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_transactions AS
        SELECT {train_sel}
        FROM read_csv_auto('{csv_path("train_transaction.csv")}', nullstr='')
    """)

    print("Inserting test_transaction.csv → stg_transactions …")
    con.execute(f"""
        INSERT INTO stg_transactions
        SELECT {test_sel}
        FROM read_csv_auto('{csv_path("test_transaction.csv")}', nullstr='')
    """)


def load_identity(con: duckdb.DuckDBPyConnection) -> None:
    train_headers = get_headers(RAW_DIR / "train_identity.csv")
    test_headers = get_headers(RAW_DIR / "test_identity.csv")

    train_sel = build_identity_select(train_headers, "train")
    test_sel = build_identity_select(test_headers, "test")

    print("Loading train_identity.csv → stg_identity …")
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_identity AS
        SELECT {train_sel}
        FROM read_csv_auto('{csv_path("train_identity.csv")}', nullstr='')
    """)

    print("Inserting test_identity.csv → stg_identity …")
    con.execute(f"""
        INSERT INTO stg_identity
        SELECT {test_sel}
        FROM read_csv_auto('{csv_path("test_identity.csv")}', nullstr='')
    """)


def print_summary(con: duckdb.DuckDBPyConnection) -> None:
    # ── Row counts ────────────────────────────────────────────────────────────
    print("\n── Row counts ──────────────────────────────────")
    for table in ("stg_transactions", "stg_identity"):
        rows = con.execute(
            f"SELECT split, COUNT(*) FROM {table} GROUP BY split ORDER BY split"
        ).fetchall()
        for split, n in rows:
            print(f"  {table} [{split}]: {n:>10,}")

    total_txn = con.execute("SELECT COUNT(*) FROM stg_transactions").fetchone()[0]
    total_id = con.execute("SELECT COUNT(*) FROM stg_identity").fetchone()[0]

    # ── Null rates: stg_transactions (one scan) ────────────────────────────────
    txn_null_cols = [
        "dist1", "dist2",
        "p_emaildomain", "r_emaildomain",
        "addr1", "addr2",
        "d2", "d6", "d7", "d8", "d9",
        "m1", "m5",
    ]
    null_exprs = ",\n    ".join(
        f"COUNT(*) - COUNT({c}) AS {c}" for c in txn_null_cols
    )
    row = con.execute(f"SELECT {null_exprs} FROM stg_transactions").fetchone()

    print(f"\n── Null rates: stg_transactions (n={total_txn:,}) ──")
    for col, null_n in zip(txn_null_cols, row):
        pct = 100 * null_n / total_txn
        bar = "█" * int(pct / 5)
        print(f"  {col:<18} {null_n:>8,}  {pct:5.1f}%  {bar}")

    # ── Null rates: stg_identity (one scan) ────────────────────────────────────
    id_null_cols = [
        "id_01", "id_02",
        "id_07", "id_08",
        "id_12", "id_15",
        "id_30", "id_31",
        "device_type", "device_info",
    ]
    null_exprs = ",\n    ".join(
        f"COUNT(*) - COUNT({c}) AS {c}" for c in id_null_cols
    )
    row = con.execute(f"SELECT {null_exprs} FROM stg_identity").fetchone()

    print(f"\n── Null rates: stg_identity (n={total_id:,}) ──")
    for col, null_n in zip(id_null_cols, row):
        pct = 100 * null_n / total_id
        bar = "█" * int(pct / 5)
        print(f"  {col:<18} {null_n:>8,}  {pct:5.1f}%  {bar}")

    # ── Identity join coverage ─────────────────────────────────────────────────
    print("\n── Identity join coverage ──────────────────────")
    rows = con.execute("""
        SELECT
            t.split,
            COUNT(*)                                              AS total_txns,
            COUNT(i.transaction_id)                               AS with_identity,
            ROUND(100.0 * COUNT(i.transaction_id) / COUNT(*), 1) AS pct
        FROM stg_transactions t
        LEFT JOIN stg_identity i USING (transaction_id)
        GROUP BY t.split
        ORDER BY t.split
    """).fetchall()
    for split, total, with_id, pct in rows:
        print(f"  {split}: {with_id:,} / {total:,} ({pct}%) have identity rows")

    # ── Fraud rate (train only) ────────────────────────────────────────────────
    fraud_total, fraud_pos = con.execute("""
        SELECT COUNT(*), SUM(is_fraud::INTEGER)
        FROM stg_transactions
        WHERE split = 'train'
    """).fetchone()
    print(f"\n── Fraud rate (train): {fraud_pos:,} / {fraud_total:,} ({100*fraud_pos/fraud_total:.2f}%)")

    # ── Type spot-check: card2/3/5 should be INTEGER ───────────────────────────
    print("\n── Type spot-check (card2/card3/card5) ─────────")
    dtypes = con.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'stg_transactions'
          AND column_name IN ('card2', 'card3', 'card5')
        ORDER BY column_name
    """).fetchall()
    for name, dtype in dtypes:
        status = "OK" if "INT" in dtype.upper() else "WARN — expected INTEGER"
        print(f"  {name}: {dtype}  [{status}]")


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    load_transactions(con)
    load_identity(con)
    print_summary(con)

    con.close()
    print(f"\nDone. Database written to {DB_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
