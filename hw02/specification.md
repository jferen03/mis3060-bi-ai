I need you to write ONE single Python script that profiles a transactions dataset. All 17 items below must live in the same file and run together in a single execution. Please do not split this into multiple scripts, notebooks, or modules. Use pandas for the data work and matplotlib for the charts. Save the script as hw02/profile_transactions.py. It should run from the repository root, so all paths below are relative to the repository root.

**Header comment block (item 17).** At the very top of the script, put a comment block that identifies the script, the dataset (data/raw/fact_transactions.csv), the author (leave a clearly marked placeholder for my name), and the date the script was generated.

**What the script must do, in this order.** Print a clear section heading for each step so the console output reads like a report.

1. Load data/raw/fact_transactions.csv into a pandas DataFrame. If the file is missing, stop with a friendly error message, not a long traceback.
2. Print the shape as rows × columns.
3. Print all column names and their data types.
4. Print the count of missing values for every column, including columns with zero.
5. Print descriptive statistics (count, mean, std, min, 25th percentile, median, 75th percentile, max) for all numeric columns.
6. Print value counts and percentages for txn_type, sorted from most to least frequent.
7. Print the unique count of clients, advisors, and securities referenced in the file. Inspect the column names to work out which columns hold those identifiers.
8. Print the earliest and latest txn_date. Make sure it is parsed as a real date, not text.
9. Check for duplicate rows by txn_id and print the duplicate count.
10. Print the mean, median, and skewness of the amount column.
11. Group by txn_type and print, for each type, the count and the mean and median amount, rounded to 2 decimal places, sorted by mean amount descending.
12. Compute the correlation matrix for shares, price, and amount, rounded to 2 decimal places, and print it. Then identify and print the three strongest correlations, excluding a variable's correlation with itself. Rank by absolute strength but show the signed value.
13. Print the minimum, maximum, and count of negative values in the shares column, broken out by txn_type.
14. If the shape is not exactly (298772, 9), print a prominent warning stating what was expected and what was found. If it matches, print a short confirmation.
15. Create and save three charts to the hw02/charts/ folder (create the folder if it doesn't exist). Every chart needs a title and labeled axes.
    - hw02/charts/hist_amount.png: a histogram of amount with vertical lines at the mean and the median, in different colors or styles, labeled clearly in a legend that includes their values.
    - hw02/charts/box_amount_by_type.png: a horizontal box plot of amount by txn_type.
    - hw02/charts/scatter_shares_amount.png: a scatter plot of shares (x-axis) vs. amount (y-axis), colored by txn_type, with a legend. With ~300k rows, use small points and transparency, or plot a random sample (and say so on the chart if you do).
    Close each figure after saving so no pop-up windows appear or block the script.
16. Save a plain-text summary of steps 2–13 to hw02/hw02_profile.txt, with the same headings and results as the console. Build the report text once, then both print it and write it to the file so they always match.
17. The header comment block described above.

**Quality expectations.**
- Running the script once must produce all console output, all three charts, and the text file, with no manual steps.
- Use straightforward, beginner-readable pandas, with a short comment above each step.
- Don't let the script crash on bad assumptions. If an expected column is missing, fail with a message that names it.

When you're done, run the script and tell me whether it completed cleanly, whether the shape check passed, and where each output file was saved.
