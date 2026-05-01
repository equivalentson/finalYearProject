from pathlib import Path
import pandas as pd

# =========================================================
# SETTINGS: CHANGE THIS FOLDER TO WHERE YOUR WEEKLY CSVs ARE
# =========================================================
folder = Path(r"C:\Users\zhafri\Desktop\Power System Economics\Python\mip_2023")

# File name pattern
pattern = "MarketIndexPrices-*.csv"

# Provider to keep for your final annual average
# Set to None if you do not want filtering
provider_to_keep = "APXMIDP"

# Output files
merged_all_file = folder / "market_index_prices_2023_merged_all.csv"
merged_filtered_file = folder / "market_index_prices_2023_merged_APXMIDP.csv"

# =========================================================
# LOAD FILES
# =========================================================
files = sorted(folder.glob(pattern))

if not files:
    raise FileNotFoundError(
        f"No files matching '{pattern}' were found in:\n{folder}"
    )

print(f"Found {len(files)} files.\n")

expected_cols = {
    "StartTime",
    "DataProvider",
    "SettlementDate",
    "SettlementPeriod",
    "Price",
    "Volume",
}

frames = []

for file in files:
    print(f"Reading: {file.name}")
    df = pd.read_csv(file)

    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"{file.name} is missing these columns: {sorted(missing)}"
        )

    frames.append(df)

# =========================================================
# MERGE ALL FILES
# =========================================================
merged = pd.concat(frames, ignore_index=True)

# Clean data types
merged["StartTime"] = pd.to_datetime(merged["StartTime"], utc=True, errors="coerce")
merged["SettlementDate"] = pd.to_datetime(merged["SettlementDate"], errors="coerce")
merged["SettlementPeriod"] = pd.to_numeric(merged["SettlementPeriod"], errors="coerce")
merged["Price"] = pd.to_numeric(merged["Price"], errors="coerce")
merged["Volume"] = pd.to_numeric(merged["Volume"], errors="coerce")

# Drop rows with missing essential values
merged = merged.dropna(subset=["StartTime", "DataProvider", "SettlementDate", "SettlementPeriod", "Price"])

# Remove exact duplicates
rows_before = len(merged)
merged = merged.drop_duplicates()
rows_after = len(merged)

# Sort nicely
merged = merged.sort_values(
    by=["StartTime", "DataProvider", "SettlementPeriod"]
).reset_index(drop=True)

# Save full merged dataset
merged.to_csv(merged_all_file, index=False)

print("\n==============================")
print("FULL MERGE COMPLETE")
print("==============================")
print(f"Rows before duplicate removal: {rows_before}")
print(f"Rows after duplicate removal : {rows_after}")
print(f"Duplicates removed           : {rows_before - rows_after}")
print(f"Saved full merged file to    : {merged_all_file}")

# =========================================================
# OPTIONAL: FILTER TO ONE PROVIDER
# =========================================================
if provider_to_keep is not None:
    filtered = merged[merged["DataProvider"] == provider_to_keep].copy()

    if filtered.empty:
        raise ValueError(
            f"No rows found for DataProvider = '{provider_to_keep}'. "
            f"Available providers are: {sorted(merged['DataProvider'].dropna().unique())}"
        )

    filtered = filtered.sort_values(
        by=["StartTime", "SettlementPeriod"]
    ).reset_index(drop=True)

    filtered.to_csv(merged_filtered_file, index=False)

    # Arithmetic mean price
    annual_avg_price = filtered["Price"].mean()

    # Volume-weighted mean price
    if filtered["Volume"].sum() > 0:
        vw_avg_price = (filtered["Price"] * filtered["Volume"]).sum() / filtered["Volume"].sum()
    else:
        vw_avg_price = None

    print("\n==============================")
    print("FILTERED FILE COMPLETE")
    print("==============================")
    print(f"Provider kept               : {provider_to_keep}")
    print(f"Rows in filtered file       : {len(filtered)}")
    print(f"Saved filtered file to      : {merged_filtered_file}")
    print(f"Arithmetic average Price    : {annual_avg_price:.4f} £/MWh")

    if vw_avg_price is not None:
        print(f"Volume-weighted avg Price   : {vw_avg_price:.4f} £/MWh")
    else:
        print("Volume-weighted avg Price   : not available (total volume = 0)")

else:
    print("\nNo provider filtering applied.")