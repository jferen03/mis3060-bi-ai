import pandas as pd

df = pd.read_csv("data/raw/fact_transactions.csv")

total_rows = len(df)
excluded_types = ["Sell", "Deposit", "Withdrawal", "Dividend", "Advisory Fee"]
excluded_rows = df["txn_type"].isin(excluded_types).sum()
remaining = total_rows - excluded_rows

print(f"Total rows:                  {total_rows:,}")
print(f"Rows of excluded types:      {excluded_rows:,}")
print(f"Total minus excluded types:  {remaining:,}")
