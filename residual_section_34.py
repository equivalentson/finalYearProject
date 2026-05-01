from pathlib import Path
import pandas as pd

from capacityScenario import (
    SEASON_WINDOWS_8760,
    _read_ninja_csv,
    _slice_by_1indexed_hours,
    size_pv_from_hourly_kw_ninja,
)


def _build_reference_pv_profile(
    pv_csv_path: str,
    calculation_type: str = "annual",
    P_ref_kW: float | None = None,
) -> tuple[pd.Series, float]:
    calculation_type = calculation_type.strip().lower()
    pv_csv_path = Path(pv_csv_path)
    base_dir = pv_csv_path.parent

    if calculation_type == "annual":
        df, cap_kW = _read_ninja_csv(pv_csv_path, P_ref_kW=P_ref_kW)

    elif calculation_type == "seasonal":
        season_files = {
            "winter": base_dir / "winter.csv",
            "spring": base_dir / "spring.csv",
            "summer": base_dir / "summer.csv",
            "autumn": base_dir / "autumn.csv",
        }
        for p in season_files.values():
            if not p.exists():
                raise FileNotFoundError(f"Missing: {p}")

        df_w,  cap_w  = _read_ninja_csv(season_files["winter"], P_ref_kW=P_ref_kW)
        df_sp, cap_sp = _read_ninja_csv(season_files["spring"], P_ref_kW=P_ref_kW)
        df_su, cap_su = _read_ninja_csv(season_files["summer"], P_ref_kW=P_ref_kW)
        df_a,  cap_a  = _read_ninja_csv(season_files["autumn"], P_ref_kW=P_ref_kW)

        for name, d in [("winter", df_w), ("spring", df_sp), ("summer", df_su), ("autumn", df_a)]:
            if len(d) != 8760:
                raise ValueError(f"{name}.csv has {len(d)} rows, expected 8760.")

        cap_kW = cap_w
        caps = [cap_w, cap_sp, cap_su, cap_a]
        if any(abs(c - cap_kW) > 1e-6 for c in caps):
            raise ValueError(f"Reference capacities differ: {caps}")

        df = pd.concat([
            _slice_by_1indexed_hours(df_w,  [(1, 1416)]),
            _slice_by_1indexed_hours(df_sp, SEASON_WINDOWS_8760["spring"]),
            _slice_by_1indexed_hours(df_su, SEASON_WINDOWS_8760["summer"]),
            _slice_by_1indexed_hours(df_a,  SEASON_WINDOWS_8760["autumn"]),
            _slice_by_1indexed_hours(df_w,  [(8017, 8760)]),
        ], ignore_index=True)

        if len(df) != 8760:
            raise ValueError(f"Stitched profile has {len(df)} rows, expected 8760.")

    else:
        raise ValueError("calculation_type must be 'annual' or 'seasonal'.")

    pv_ref_MW = pd.to_numeric(df["electricity"], errors="coerce").fillna(0.0).clip(lower=0.0) / 1000.0

    if "time" in df.columns:
        t = pd.to_datetime(df["time"], errors="coerce")
        if t.notna().all() and t.is_monotonic_increasing:
            pv_ref_MW.index = t

    return pv_ref_MW.rename("pv_reference_MW"), cap_kW / 1000.0


def read_gridwatch_hourly_demand(csv_path: str) -> pd.Series:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    time_col   = next((c for c in ["timestamp", "time", "datetime", "date"] if c in df.columns), None)
    demand_col = next((c for c in ["demand", "demand_mw", "load", "load_mw"] if c in df.columns), None)

    if time_col is None:
        raise ValueError(f"No timestamp column found. Got: {list(df.columns)}")
    if demand_col is None:
        raise ValueError(f"No demand column found. Got: {list(df.columns)}")

    df[time_col]   = pd.to_datetime(df[time_col], errors="coerce")
    df[demand_col] = pd.to_numeric(df[demand_col], errors="coerce")
    df = df.dropna(subset=[time_col, demand_col]).sort_values(time_col)

    return (
        df.set_index(time_col)[demand_col]
        .resample("1h")
        .mean()
        .dropna()
        .rename("demand_MW")
    )


def _drop_feb29_if_present(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        return series
    mask = ~((series.index.month == 2) & (series.index.day == 29))
    return series.loc[mask]


def _align_hourly_series(demand_MW: pd.Series, pv_MW: pd.Series) -> tuple[pd.Series, pd.Series]:
    if isinstance(demand_MW.index, pd.DatetimeIndex) and isinstance(pv_MW.index, pd.DatetimeIndex):
        demand_tmp = _drop_feb29_if_present(demand_MW)
        pv_tmp     = _drop_feb29_if_present(pv_MW)
        joined = pd.concat(
            [demand_tmp.rename("demand_MW"), pv_tmp.rename("pv_generation_MW")],
            axis=1, join="inner"
        ).dropna()
        if len(joined) >= 8000:
            return joined["demand_MW"], joined["pv_generation_MW"]

    n = min(len(demand_MW), len(pv_MW))
    if n == 0:
        raise ValueError("No overlapping hourly data.")

    return (
        demand_MW.reset_index(drop=True).iloc[:n].rename("demand_MW"),
        pv_MW.reset_index(drop=True).iloc[:n].rename("pv_generation_MW"),
    )


def calculate_residual_import_export(
    pv_csv_path: str,
    demand_csv_path: str,
    installed_capacity_MW: float | None = None,
    penetration: float | None = None,
    calculation_type: str = "annual",
    P_ref_kW: float | None = None,
    output_csv_path: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    demand_hourly_MW = read_gridwatch_hourly_demand(demand_csv_path)
    pv_ref_MW, ref_capacity_MW = _build_reference_pv_profile(
        pv_csv_path=pv_csv_path,
        calculation_type=calculation_type,
        P_ref_kW=P_ref_kW,
    )

    if installed_capacity_MW is None:
        if penetration is None:
            raise ValueError("Provide either installed_capacity_MW or penetration.")

        p = float(penetration)
        if p > 1:
            p = p / 100.0

        annual_demand_MWh = float(demand_hourly_MW.sum())
        sizing = size_pv_from_hourly_kw_ninja(
            csv_path=pv_csv_path,
            E_required=p * annual_demand_MWh,
            E_required_unit="MWh",
            calculation_type=calculation_type,
            P_ref_kW=P_ref_kW,
        )
        installed_capacity_MW = float(sizing["P_required_MW"])

    pv_generation_MW = (pv_ref_MW * (installed_capacity_MW / ref_capacity_MW)).rename("pv_generation_MW")
    demand_aligned_MW, pv_aligned_MW = _align_hourly_series(demand_hourly_MW, pv_generation_MW)

    result = pd.DataFrame({"demand_MW": demand_aligned_MW, "pv_generation_MW": pv_aligned_MW})
    result["residual_demand_MW"] = result["demand_MW"] - result["pv_generation_MW"]
    result["P_import_MW"]        = result["residual_demand_MW"].clip(lower=0.0)
    result["P_export_MW"]        = (-result["residual_demand_MW"]).clip(lower=0.0)
    result["self_supply_MW"]     = result[["demand_MW", "pv_generation_MW"]].min(axis=1)

    annual_summary = {
        "rows_used"                : int(len(result)),
        "reference_capacity_MW"    : float(ref_capacity_MW),
        "installed_capacity_MW"    : float(installed_capacity_MW),
        "annual_demand_MWh"        : float(result["demand_MW"].sum()),
        "annual_pv_generation_MWh" : float(result["pv_generation_MW"].sum()),
        "annual_import_MWh"        : float(result["P_import_MW"].sum()),
        "annual_export_MWh"        : float(result["P_export_MW"].sum()),
        "annual_self_supply_MWh"   : float(result["self_supply_MW"].sum()),
    }

    if output_csv_path:
        out = Path(output_csv_path)
        result.to_csv(out, index=True)
        pd.DataFrame([annual_summary]).to_csv(out.with_name(out.stem + "_summary.csv"), index=False)

    return result, annual_summary


if __name__ == "__main__":
    base_dir = Path(__file__).parent

    while True:
        calc_type = input("Calculation type (annual / seasonal): ").strip().lower()
        if calc_type in ("annual", "seasonal"):
            break
        print("Enter 'annual' or 'seasonal'.")

    pv_csv_path = base_dir / "annual.csv"
    if calc_type == "annual":
        if not pv_csv_path.exists():
            raise FileNotFoundError(f"Not found: {pv_csv_path}")
        print(f"Using: {pv_csv_path.name}")
    else:
        print("Seasonal mode — will use winter.csv, spring.csv, summer.csv, autumn.csv")

    demand_csv_path = base_dir / "gridwatch.csv"
    if not demand_csv_path.exists():
        raise FileNotFoundError(f"Not found: {demand_csv_path}")

    while True:
        mode = input("Use installed capacity or penetration? (capacity / penetration): ").strip().lower()
        if mode in ("capacity", "penetration"):
            break
        print("Enter 'capacity' or 'penetration'.")

    installed_capacity_MW = None
    penetration = None

    if mode == "capacity":
        while True:
            try:
                installed_capacity_MW = float(input("Installed PV capacity (MW): "))
                break
            except ValueError:
                print("Enter a valid number.")
    else:
        while True:
            try:
                penetration = float(input("PV penetration (e.g. 0.1 or 10): "))
                break
            except ValueError:
                print("Enter a valid number.")

    hourly_result, annual_summary = calculate_residual_import_export(
        pv_csv_path=str(pv_csv_path),
        demand_csv_path=str(demand_csv_path),
        installed_capacity_MW=installed_capacity_MW,
        penetration=penetration,
        calculation_type=calc_type,
        output_csv_path=str(base_dir / "section_34_output.csv"),
    )

    print("\n----- Annual Summary -----")
    for k, v in annual_summary.items():
        print(f"{k}: {v}")
