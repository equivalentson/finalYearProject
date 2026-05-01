from pathlib import Path
import sys
import pandas as pd

# paths
base_dir   = Path(__file__).parent
mip_folder = Path(r"C:\Users\zhafri\Desktop\Power System Economics\Python\mip_2023")

pv_csv     = base_dir / "annual.csv"
demand_csv = base_dir / "gridwatch.csv"

# apxmidp filter
mip_pattern = "MarketIndexPrices-*.csv"
provider    = "APXMIDP"
calc_type   = "annual"

# dcf assumptions
fixed_price   = 93.4393  # £/MWh
export_price  = 0.0
capex_per_mw  = 462_000  # £/MW
discount_rate = 0.05
project_life  = 35

penetration_levels = [0.0, 0.05, 0.10, 0.20, 0.40, 0.60]

sys.path.insert(0, str(base_dir))
from residual_section_34 import calculate_residual_import_export


# load and merge weekly mip files
print("Loading MIP data...")
mip_files = sorted(mip_folder.glob(mip_pattern))
if not mip_files:
    raise FileNotFoundError(f"No MIP files found in {mip_folder}")
print(f"  Found {len(mip_files)} weekly files.")

mip_all = pd.concat([pd.read_csv(f) for f in mip_files], ignore_index=True)
mip_all["StartTime"] = pd.to_datetime(mip_all["StartTime"], utc=True, errors="coerce")
mip_all["Price"]     = pd.to_numeric(mip_all["Price"], errors="coerce")
mip_all = mip_all.dropna(subset=["StartTime", "Price"]).drop_duplicates()

mip_apx = mip_all[mip_all["DataProvider"] == provider].copy()
mip_apx = mip_apx.sort_values("StartTime").reset_index(drop=True)
print(f"  APXMIDP rows: {len(mip_apx)}")

# resample 30-min -> hourly, convert to local time
mip_apx    = mip_apx.set_index("StartTime").sort_index()
mip_hourly = mip_apx["Price"].resample("1h").mean().dropna()
mip_hourly.index = mip_hourly.index.tz_convert("Europe/London").tz_localize(None)

print(f"  Hourly series: {len(mip_hourly)} hours")
print(f"  Avg: £{mip_hourly.mean():.4f}/MWh | Min: £{mip_hourly.min():.2f} | Max: £{mip_hourly.max():.2f}")


def npv_annuity(net_benefit, capex, r, n):
    if capex == 0 or net_benefit <= 0:
        return 0.0
    return -capex + net_benefit * (1 - (1 + r)**(-n)) / r


# scenario loop
print("\n" + "="*70)
print("RUNNING SCENARIOS")
print("="*70)

results = []

for p in penetration_levels:
    label = f"{int(p*100)}%"

    hourly_df, summary = calculate_residual_import_export(
        pv_csv_path      = str(pv_csv),
        demand_csv_path  = str(demand_csv),
        penetration      = p,
        calculation_type = calc_type,
    )

    c_installed = summary["installed_capacity_MW"]
    ann_pv_gen  = summary["annual_pv_generation_MWh"]
    ann_self    = summary["annual_self_supply_MWh"]
    ann_imports = summary["annual_import_MWh"]
    ann_exports = summary["annual_export_MWh"]

    hourly_df.index = pd.to_datetime(hourly_df.index)
    aligned = hourly_df.join(mip_hourly.rename("price"), how="inner")

    imports_h     = aligned["P_import_MW"]
    self_supply_h = aligned["self_supply_MW"]
    price_h       = aligned["price"]

    # variable price: value self-supply at each hour's market price
    ann_avoided_var = (self_supply_h * price_h).sum()
    ann_proc_var    = (imports_h * price_h).sum()
    net_benefit_var = ann_avoided_var + ann_exports * export_price

    # fixed price: flat rate across the year
    net_benefit_fix = ann_self * fixed_price + ann_exports * export_price

    capex   = c_installed * capex_per_mw
    npv_var = npv_annuity(net_benefit_var, capex, discount_rate, project_life)
    npv_fix = npv_annuity(net_benefit_fix, capex, discount_rate, project_life)

    results.append({
        "Scenario"                          : label,
        "Installed Capacity (MW)"           : round(c_installed, 2),
        "Annual PV Gen (GWh)"               : round(ann_pv_gen / 1e3, 2),
        "Self-Supply (GWh)"                 : round(ann_self / 1e3, 2),
        "Exports (GWh)"                     : round(ann_exports / 1e3, 2),
        "Imports (GWh)"                     : round(ann_imports / 1e3, 2),
        "Hours aligned w/ MIP"              : len(aligned),
        "Proc Cost - Variable (£bn)"        : round(ann_proc_var / 1e9, 3),
        "Avoided Proc - Variable (£bn)"     : round(ann_avoided_var / 1e9, 3),
        "Net Benefit - Variable (£bn)"      : round(net_benefit_var / 1e9, 3),
        "NPV - Variable Price (£bn)"        : round(npv_var / 1e9, 3),
        "Net Benefit - Fixed (£bn)"         : round(net_benefit_fix / 1e9, 3),
        "NPV - Fixed Price (£bn)"           : round(npv_fix / 1e9, 3),
        "CAPEX (£bn)"                       : round(capex / 1e9, 3),
        "Ann Avoided Proc - Fixed (£/yr)"   : round(net_benefit_fix, 2),
        "Ann Avoided Proc - Variable (£/yr)": round(net_benefit_var, 2),
        "_capex_exact"                      : capex,
        "_nb_fix_exact"                     : net_benefit_fix,
        "_nb_var_exact"                     : net_benefit_var,
    })

    print(f"  {label}: capacity={c_installed:.1f} MW | "
          f"self-supply={ann_self/1e3:.1f} GWh | "
          f"NPV-fix=£{npv_fix/1e9:.3f}bn | "
          f"NPV-var=£{npv_var/1e9:.3f}bn")


# project life sensitivity (every 2 years, include year 35)
project_life_steps = list(range(0, project_life, 2)) + [project_life]

life_rows = []
for row in results:
    capex  = row["_capex_exact"]
    nb_var = row["_nb_var_exact"]
    nb_fix = row["_nb_fix_exact"]

    for n in project_life_steps:
        if n == 0 or capex == 0:
            npv_var_n = -capex if capex > 0 else 0.0
            npv_fix_n = -capex if capex > 0 else 0.0
        else:
            annuity   = (1 - (1 + discount_rate)**(-n)) / discount_rate
            npv_var_n = -capex + nb_var * annuity
            npv_fix_n = -capex + nb_fix * annuity

        life_rows.append({
            "Scenario"                  : row["Scenario"],
            "Project Life (years)"      : n,
            "CAPEX (£bn)"               : round(capex / 1e9, 3),
            "NPV - Fixed Price (£bn)"   : round(npv_fix_n / 1e9, 3),
            "NPV - Variable Price (£bn)": round(npv_var_n / 1e9, 3),
        })

life_df = pd.DataFrame(life_rows)


# print results
results_df = pd.DataFrame(results)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)

print("\n--- TECHNICAL RESULTS ---")
print(results_df[["Scenario", "Installed Capacity (MW)", "Annual PV Gen (GWh)",
                   "Self-Supply (GWh)", "Exports (GWh)", "Imports (GWh)"]].to_string(index=False))

print("\n--- NPV COMPARISON: FIXED vs VARIABLE PRICE (35 years) ---")
print(results_df[["Scenario", "CAPEX (£bn)", "Net Benefit - Fixed (£bn)",
                   "NPV - Fixed Price (£bn)", "Net Benefit - Variable (£bn)",
                   "NPV - Variable Price (£bn)"]].to_string(index=False))

print(f"\n  Fixed price : £{fixed_price}/MWh")
print(f"  Avg variable: £{mip_hourly.mean():.4f}/MWh")

print("\n--- ANNUAL AVOIDED PROCUREMENT (£/yr) ---")
print(results_df[["Scenario", "Ann Avoided Proc - Fixed (£/yr)",
                   "Ann Avoided Proc - Variable (£/yr)"]].to_string(index=False))

print("\n--- NPV BY PROJECT LIFE ---")
for price_type in ["Fixed", "Variable"]:
    col = f"NPV - {price_type} Price (£bn)"
    pivot = life_df.pivot(index="Project Life (years)", columns="Scenario", values=col)
    pivot = pivot[[s for s in ["0%", "5%", "10%", "20%", "40%", "60%"] if s in pivot.columns]]
    print(f"\n  {price_type} Price NPV (£bn):")
    print(pivot.to_string())


# save
results_df.to_csv(base_dir / "sensitivity_results.csv", index=False)
life_df.to_csv(base_dir / "sensitivity_results_by_project_life.csv", index=False)
print(f"\nSaved: sensitivity_results.csv")
print(f"Saved: sensitivity_results_by_project_life.csv")
