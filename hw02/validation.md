# HW02 Validation: `fact_transactions.csv`

THIS IS 2A: Known-Answer Benchmarks!!!

Values below come from running `hw02/hw02_eda.py` from the repository root (see `hw02/hw02_profile.txt` and the console output).

| Check | Expected | Your Script Produced | Match? | Notes |
|---|---|---|---|---|
| Dataset shape | (298772, 9) | (298772, 9) | Yes | Script also prints "OK: Shape matches the expected (298772, 9)". |
| Null count — security_id | 101,597 | 101,597 | Yes | Nulls are the non-security transactions (Deposit, Withdrawal, Advisory Fee), which have no security. |
| Null count — amount | 0 | 0 | Yes | Every transaction has an amount. |
| Unique txn_type values | 6 | 6 | Yes | Buy, Sell, Dividend, Deposit, Advisory Fee, Withdrawal. |
| Count of Buy transactions | 83,556 | 83,556 | Yes | 27.97% of all transactions, the most frequent type. |
| txn_date data type | object | datetime64[us] | No | The script deliberately converts `txn_date` from text to a real date. As loaded, the column is text (`object`, shown as `str` in pandas 3). See explanation below. |
| Earliest txn_date | 2020-01-01 | 2020-01-01 | Yes | Found after converting to dates, so the ordering is chronological. |
| Latest txn_date | 2024-12-30 | 2024-12-30 | Yes | Same as above. |
| Duplicate txn_id count | 0 | 0 | Yes | `txn_id` is unique for all 298,772 rows. |
| Mean amount | $54,075.17 | $54,075.17 | Yes | Unrounded mean is 54,075.1665. |
| Median amount | $41,220.48 | $41,220.49 (report) / 41,220.48 (stats table) | No | The true median is exactly 41,220.485, so the last cent depends on the rounding rule. See explanation below. |
| Skewness of amount | 1.15 | 1.15 | Yes | Unrounded value is 1.1463. Positive skew: the mean is above the median. |
| Correlation shares–amount | 0.65 | 0.65 | Yes | |
| Correlation price–amount | 0.64 | 0.64 | Yes | |
| Correlation shares–price | 0.00 | 0.00 | Yes | Shares and price are essentially uncorrelated. |
| Negative shares count (Buy only) | 836 | 836 | Yes | All 836 negative-share rows are Buy transactions; no other type has any. |
| Profile file created | Yes | Yes | Yes | `hw02/hw02_profile.txt` exists. |
| Chart files created (3) | Yes | Yes | Yes | `hist_amount.png`, `box_amount_by_type.png` and `scatter_shares_amount.png` are in `hw02/charts/`. |

## For any row where Match = No

**txn_date data type (expected `object`, script shows `datetime64[us]`)**

- **What happened:** the CSV stores dates as text like `12/16/2023`, so the raw column loads as text (`object`, or `str` in pandas 3). My script converts it to a real date type right after loading, so the data type printed in step 3 is `datetime64[us]`.
- **Why it isn't a data problem:** the conversion is intentional. It is needed so that the earliest and latest dates in step 8 are chronological. Comparing the raw text would sort `"1/1/2020"` and `"9/9/2024"` alphabetically and give a wrong answer.
- **Conclusion:** the difference is a correct, deliberate improvement, not an error. The raw column does match the expected type (text) before the conversion.

**Median amount (expected $41,220.48, script shows $41,220.49 in one place)**

- **What happened:** the true median is exactly 41,220.485, which sits halfway between two cents. The step 10 report line formats it with Python's `:,.2f`, which shows 41,220.49. The step 5 stats table uses `round(2)`, which shows 41,220.48. The two rounding methods break the tie in different directions.
- **Why it isn't a data problem:** the underlying value is identical in both places. The expected 41,220.48 and the script's 41,220.49 are the same number, 41,220.485, rounded two different ways. The one-cent difference is only display rounding.
- **Conclusion:** the data and the calculation are correct. If an exact match to $41,220.48 is required, ask Claude Cowork to round the median with the same method as the benchmark (round half to even) so both places agree.

THIS IS 2B: Explain the Code and Output!!!

1. After looking through the terminal vs the output that Claude expected, there is not a singular thing that is different. Every single number is exactly the same and the output tables look ide3ntical as well. Even the rounding is exactly the same.

2. It flagged 8 items but specifically emphasized the first. 

836 negative Buy shares

amount is always positive and unsigned

The dataset looks synthetic

Dividend rows carry shares and price

Advisory fee amounts are very skewed

Transaction volume by year (growth, then a 2024 drop)

Deposits and withdrawals have a hard floor and cap

Descriptive stats for ID columns are meaningless

3. Claude did note the 101,597 null values but didn't seem to believe that they should be adjusted. This is the output:

security_id, shares and price are each missing 101,597 rows.
That equals Deposit, Withdrawal and Advisory Fee rows (35,981 + 29,850 + 35,766).
These are structural blanks, not data errors. Cash movements and fees have no security. Don't impute them.

4. My Claude did not flag the txn_date column as a concern. 

5. Yes. The three images are clear representations of what the output should be. I will say that the scatter shares amount graph is pretty ineffective due to the 826 negative buy orders. It completely messes up the value of the graphs because they are outliers. 

6. Question: "Is there any value in converting the negative buy orders to be null values as they are definetly outliers and skew some of the graphs?"

Answer: Nulling them has some value, but I'd only do it as a fallback.

Why nulling isn't the best first move

They aren't outliers in magnitude. Their absolute values fall in the normal range (about 1 to 500), and their amount and price are valid. My check showed |shares × price| matches amount to within half a cent on every one of these rows. Only the sign is wrong.
Nulling throws away information. If they are mislabeled or sign-flipped rows, the true shares are recoverable, and blanking them turns a fixable error into permanent missing data.
It would blur your data-quality finding. After nulling, the profile would show extra missing shares on Buy rows. That hides a real problem worth reporting.

How much they skew the graphs

They are 836 of 298,772 rows (0.28%), or 1% of Buy rows.
The only chart affected is the scatter of shares vs amount, where a few points sit at negative x.
The histogram and box plot use amount, which those rows don't distort. The correlation shifts only slightly.

What I'd do instead, in order

Add a flag column, for example neg_shares_flag, and leave the raw data untouched.
Get the answer from the data owner:
If they are sign errors, take the absolute value.
If they are mislabeled Sells, relabel them.
If you can't resolve it, exclude them from share-based analysis. That means the scatter, correlation, and any position or cost-basis work. Keep them for amount-only analysis.
If you do null them, do it in a cleaned copy, never the raw file. Document the count (836) and the reason, and keep the flag so the change is traceable.

Whichever option you pick, do the cleaning in a separate script or step so the raw data stays reproducible.