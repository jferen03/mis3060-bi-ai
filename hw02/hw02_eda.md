# hw02_eda.py

```python
# =============================================================================
# Script:   hw02_eda.py
# Purpose:  Exploratory data analysis (EDA) profile of the transactions dataset.
#           Prints a profile report, saves it to a text file, and saves three charts.
# Dataset:  data/raw/fact_transactions.csv
# Author:   [YOUR NAME HERE]
# Generated: 2026-09-20
#
# Run from the repository root:  python hw02/hw02_eda.py
# Outputs:  hw02/hw02_profile.txt
#           hw02/charts/hist_amount.png
#           hw02/charts/box_amount_by_type.png
#           hw02/charts/scatter_shares_amount.png
# =============================================================================

import os
import sys

import matplotlib

matplotlib.use("Agg")  # save charts to files only; never open pop-up windows
import matplotlib.pyplot as plt
import pandas as pd

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DATA_PATH = "data/raw/fact_transactions.csv"
CHARTS_DIR = "hw02/charts"
PROFILE_PATH = "hw02/hw02_profile.txt"
EXPECTED_SHAPE = (298772, 9)
REQUIRED_COLUMNS = [
    "txn_id", "client_id", "advisor_id", "security_id",
    "txn_date", "txn_type", "shares", "price", "amount",
]

# Show full tables instead of truncating them with "..."
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

# The report text is built once, then both printed and saved to a file.
report_lines = []


def add(text=""):
    """Add a line (or block of text) to the report."""
    report_lines.append(str(text))


def heading(title):
    """Add a section heading to the report."""
    add()
    add("=" * 70)
    add(title)
    add("=" * 70)


# ---------------------------------------------------------------------------
# 1. Load the data
# ---------------------------------------------------------------------------
if not os.path.exists(DATA_PATH):
    sys.exit(
        f"ERROR: Could not find '{DATA_PATH}'. "
        "Run this script from the repository root and check the file location."
    )

df = pd.read_csv(DATA_PATH)

# Stop with a clear message if an expected column is missing
missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
if missing_cols:
    sys.exit(f"ERROR: The data file is missing expected column(s): {missing_cols}")

# Treat txn_date as a real date (not text) so earliest/latest are chronological
df["txn_date"] = pd.to_datetime(df["txn_date"], format="%m/%d/%Y", errors="coerce")

add("HW02 - Profile of data/raw/fact_transactions.csv")
add("Generated: 2026-09-20")

# ---------------------------------------------------------------------------
# 2. Shape
# ---------------------------------------------------------------------------
heading("2. Shape (rows x columns)")
add(f"{df.shape[0]:,} rows x {df.shape[1]} columns")

# ---------------------------------------------------------------------------
# 3. Column names and data types
# ---------------------------------------------------------------------------
heading("3. Column Names and Data Types")
add(df.dtypes.to_string())

# ---------------------------------------------------------------------------
# 4. Missing values per column
# ---------------------------------------------------------------------------
heading("4. Missing Values per Column")
add(df.isna().sum().to_string())

# ---------------------------------------------------------------------------
# 5. Descriptive statistics for numeric columns
#    (count, mean, std, min, 25%, 50% = median, 75%, max)
# ---------------------------------------------------------------------------
heading("5. Descriptive Statistics (numeric columns)")
add(df.describe(include="number").round(2).to_string())

# ---------------------------------------------------------------------------
# 6. txn_type value counts and percentages (most to least frequent)
# ---------------------------------------------------------------------------
heading("6. Transaction Type Breakdown (txn_type)")
type_counts = df["txn_type"].value_counts()  # sorted most to least frequent
type_pct = (type_counts / type_counts.sum() * 100).round(2)
type_table = pd.DataFrame({"count": type_counts, "percent": type_pct})
add(type_table.to_string())

# ---------------------------------------------------------------------------
# 7. Unique clients, advisors, and securities
# ---------------------------------------------------------------------------
heading("7. Unique Entities")
add(f"Unique clients:    {df['client_id'].nunique():,}")
add(f"Unique advisors:   {df['advisor_id'].nunique():,}")
add(f"Unique securities: {df['security_id'].nunique():,}")

# ---------------------------------------------------------------------------
# 8. Date range
# ---------------------------------------------------------------------------
heading("8. Date Range (txn_date)")
add(f"Earliest txn_date: {df['txn_date'].min().date()}")
add(f"Latest txn_date:   {df['txn_date'].max().date()}")

# ---------------------------------------------------------------------------
# 9. Duplicate check by txn_id
# ---------------------------------------------------------------------------
heading("9. Duplicate Check (txn_id)")
add(f"Duplicate txn_id count: {df['txn_id'].duplicated().sum():,}")

# ---------------------------------------------------------------------------
# 10. Amount: mean, median, skewness
# ---------------------------------------------------------------------------
heading("10. Amount Summary")
amount_mean = df["amount"].mean()
amount_median = df["amount"].median()
add(f"Mean:     {amount_mean:,.2f}")
add(f"Median:   {amount_median:,.2f}")
add(f"Skewness: {df['amount'].skew():.2f}")

# ---------------------------------------------------------------------------
# 11. Amount by transaction type (sorted by mean amount, highest first)
# ---------------------------------------------------------------------------
heading("11. Amount by Transaction Type")
by_type = (
    df.groupby("txn_type")["amount"]
    .agg(count="count", mean_amount="mean", median_amount="median")
    .round(2)
    .sort_values("mean_amount", ascending=False)
)
add(by_type.to_string())

# ---------------------------------------------------------------------------
# 12. Correlation matrix (shares, price, amount) and top three correlations
# ---------------------------------------------------------------------------
heading("12. Correlation Matrix (shares, price, amount)")
corr = df[["shares", "price", "amount"]].corr().round(2)
add(corr.to_string())

# Build every distinct pair (skipping a variable paired with itself)
pairs = []
cols = list(corr.columns)
for i in range(len(cols)):
    for j in range(i + 1, len(cols)):
        pairs.append((cols[i], cols[j], corr.loc[cols[i], cols[j]]))

# Rank by absolute strength, but show the signed value
pairs.sort(key=lambda p: abs(p[2]), reverse=True)
add()
add("Three strongest correlations (ranked by absolute strength):")
for rank, (var_a, var_b, value) in enumerate(pairs[:3], start=1):
    add(f"  {rank}. {var_a} vs {var_b}: {value:.2f}")

# ---------------------------------------------------------------------------
# 13. Shares: min, max, and negative count by transaction type
# ---------------------------------------------------------------------------
heading("13. Shares by Transaction Type (min, max, negative count)")
shares_by_type = df.groupby("txn_type")["shares"].agg(
    min_shares="min",
    max_shares="max",
    negative_count=lambda s: int((s < 0).sum()),
)
add(shares_by_type.to_string())

# ---------------------------------------------------------------------------
# Print the report (steps 2-13) and save it to a text file
# ---------------------------------------------------------------------------
report_text = "\n".join(report_lines)
print(report_text)

os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
with open(PROFILE_PATH, "w", encoding="utf-8") as f:
    f.write(report_text + "\n")

# ---------------------------------------------------------------------------
# 14. Shape check
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("14. Shape Check")
print("=" * 70)
if df.shape != EXPECTED_SHAPE:
    print(
        f"WARNING: Unexpected shape! Expected {EXPECTED_SHAPE}, found {df.shape}."
    )
else:
    print(f"OK: Shape matches the expected {EXPECTED_SHAPE}.")

# ---------------------------------------------------------------------------
# 15. Charts
# ---------------------------------------------------------------------------
os.makedirs(CHARTS_DIR, exist_ok=True)

# Chart 1: histogram of amount with mean and median lines
fig, ax = plt.subplots(figsize=(10, 6))
ax.hist(df["amount"].dropna(), bins=60, color="steelblue", edgecolor="white")
ax.axvline(amount_mean, color="red", linestyle="--", linewidth=2,
           label=f"Mean: {amount_mean:,.2f}")
ax.axvline(amount_median, color="green", linestyle="-", linewidth=2,
           label=f"Median: {amount_median:,.2f}")
ax.set_title("Distribution of Transaction Amount")
ax.set_xlabel("Amount")
ax.set_ylabel("Number of Transactions")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(CHARTS_DIR, "hist_amount.png"), dpi=150)
plt.close(fig)

# Chart 2: horizontal box plot of amount by txn_type
type_order = list(type_counts.index)
box_data = [df.loc[df["txn_type"] == t, "amount"].dropna() for t in type_order]
fig, ax = plt.subplots(figsize=(10, 6))
ax.boxplot(box_data, orientation="horizontal", tick_labels=type_order)
ax.set_title("Transaction Amount by Transaction Type")
ax.set_xlabel("Amount")
ax.set_ylabel("Transaction Type")
fig.tight_layout()
fig.savefig(os.path.join(CHARTS_DIR, "box_amount_by_type.png"), dpi=150)
plt.close(fig)

# Chart 3: scatter of shares (x) vs amount (y), colored by txn_type.
# ~300k points is too many to read, so plot a random sample.
scatter_df = df.dropna(subset=["shares", "amount"])
sample_size = min(20000, len(scatter_df))
scatter_sample = scatter_df.sample(n=sample_size, random_state=42)

fig, ax = plt.subplots(figsize=(10, 6))
for txn_type, group in scatter_sample.groupby("txn_type"):
    ax.scatter(group["shares"], group["amount"], s=8, alpha=0.4, label=txn_type)
ax.set_title(
    f"Shares vs Amount by Transaction Type "
    f"(random sample of {sample_size:,} rows)"
)
ax.set_xlabel("Shares")
ax.set_ylabel("Amount")
ax.legend(title="Transaction Type", markerscale=2)
fig.tight_layout()
fig.savefig(os.path.join(CHARTS_DIR, "scatter_shares_amount.png"), dpi=150)
plt.close(fig)

print()
print("=" * 70)
print("15. Charts and Files Saved")
print("=" * 70)
print(f"  {CHARTS_DIR}/hist_amount.png")
print(f"  {CHARTS_DIR}/box_amount_by_type.png")
print(f"  {CHARTS_DIR}/scatter_shares_amount.png")
print(f"  {PROFILE_PATH}")
```
