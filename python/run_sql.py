"""Execute the SQL layer pipeline against the DuckDB database in order."""
import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "duckdb" / "fraud.duckdb"

SQL_STEPS = [
    ("int_transactions_enriched",  "sql/intermediate/int_transactions_enriched.sql"),
    ("fct_fraud_analysis",         "sql/marts/fct_fraud_analysis.sql"),
    ("agg_fraud_by_email_domain",  "sql/marts/agg_fraud_by_email_domain.sql"),
    ("rule_based_scoring",         "sql/scoring/rule_based_scoring.sql"),
]

def main():
    root = Path(__file__).parent.parent
    con = duckdb.connect(str(DB_PATH))

    for table_name, sql_path in SQL_STEPS:
        full_path = root / sql_path
        sql = full_path.read_text()
        print(f"Running {sql_path} ...", end=" ", flush=True)
        con.execute(sql)
        (row_count,) = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        print(f"{row_count:,} rows -> {table_name}")

    con.close()

if __name__ == "__main__":
    main()
