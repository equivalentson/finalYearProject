import re
from pathlib import Path
import pandas as pd

# season hour windows (1-indexed, inclusive) for 8760-hour year
SEASON_WINDOWS_8760 = {
    "winter": [(1, 1416), (8017, 8760)],
    "spring": [(1417, 3624)],
    "summer": [(3625, 5832)],
    "autumn": [(5833, 8016)],
}


def _extract_capacity_kW(file_text: str) -> float | None:
    patterns = [
        r'""capacity""\s*:\s*""([0-9]*\.?[0-9]+)""',
        r'"capacity"\s*:\s*"([0-9]*\.?[0-9]+)"',
        r'"capacity"\s*:\s*([0-9]*\.?[0-9]+)',
    ]
    for p in patterns:
        m = re.search(p, file_text)
        if m:
            return float(m.group(1))
    return None


def _find_table_header_idx(file_text: str) -> int:
    for i, line in enumerate(file_text.splitlines()):
        if line.startswith("time,"):
            return i
    raise ValueError("Could not find data table header.")


def _read_ninja_csv(csv_path: Path, P_ref_kW: float | None = None) -> tuple[pd.DataFrame, float]:
    text = csv_path.read_text(encoding="utf-8", errors="ignore")

    cap_kW = _extract_capacity_kW(text)
    if cap_kW is None:
        if P_ref_kW is None:
            raise ValueError(f"Reference capacity not found in {csv_path.name}. Pass P_ref_kW manually.")
        cap_kW = float(P_ref_kW)

    header_idx = _find_table_header_idx(text)
    df = pd.read_csv(csv_path, skiprows=header_idx)

    if "electricity" not in df.columns:
        raise ValueError(f"{csv_path.name}: 'electricity' column not found. Got: {list(df.columns)}")

    return df, cap_kW


def _slice_by_1indexed_hours(df: pd.DataFrame, windows_1idx: list[tuple[int, int]]) -> pd.DataFrame:
    parts = []
    n = len(df)
    for start_1, end_1 in windows_1idx:
        start_0 = start_1 - 1
        end_0_excl = end_1
        if start_0 < 0 or start_0 >= n:
            continue
        parts.append(df.iloc[start_0:min(end_0_excl, n)])
    if not parts:
        raise ValueError("Slicing produced zero rows.")
    return pd.concat(parts, ignore_index=True)


def _median_dt_hours(df: pd.DataFrame) -> float:
    dt_hours = 1.0
    if "time" in df.columns:
        t = pd.to_datetime(df["time"], errors="coerce")
        dth = t.diff().dt.total_seconds() / 3600.0
        if dth.dropna().size > 0:
            dt_hours = float(dth.dropna().median())
    return dt_hours


def size_pv_from_hourly_kw_ninja(
    csv_path: str,
    E_required: float,
    E_required_unit: str = "MWh",
    extra_loss_fraction: float = 0.0,
    calculation_type: str = "annual",
    P_ref_kW: float | None = None
):
    calculation_type = calculation_type.strip().lower()
    csv_path = Path(csv_path)
    base_dir = csv_path.parent

    if calculation_type == "annual":
        df, cap_kW = _read_ninja_csv(csv_path, P_ref_kW=P_ref_kW)
        if len(df) not in (8760, 8784):
            print(f"WARNING: {csv_path.name} has {len(df)} rows (expected 8760 or 8784).")

    elif calculation_type == "seasonal":
        season_files = {
            "winter": base_dir / "winter.csv",
            "spring": base_dir / "spring.csv",
            "summer": base_dir / "summer.csv",
            "autumn": base_dir / "autumn.csv",
        }
        for p in season_files.values():
            if not p.exists():
                raise FileNotFoundError(f"Missing seasonal file: {p.name}")

        df_w,  cap_w  = _read_ninja_csv(season_files["winter"], P_ref_kW=P_ref_kW)
        df_sp, cap_sp = _read_ninja_csv(season_files["spring"], P_ref_kW=P_ref_kW)
        df_su, cap_su = _read_ninja_csv(season_files["summer"], P_ref_kW=P_ref_kW)
        df_a,  cap_a  = _read_ninja_csv(season_files["autumn"], P_ref_kW=P_ref_kW)

        for name, d in [("winter", df_w), ("spring", df_sp), ("summer", df_su), ("autumn", df_a)]:
            if len(d) != 8760:
                raise ValueError(f"{name}.csv has {len(d)} rows, expected 8760.")

        caps   = [cap_w, cap_sp, cap_su, cap_a]
        cap_kW = cap_w
        if any(abs(c - cap_kW) > 1e-6 for c in caps):
            raise ValueError(f"Reference capacities differ across season files: {caps}")

        winter_part1 = _slice_by_1indexed_hours(df_w,  [(1, 1416)])
        spring_part  = _slice_by_1indexed_hours(df_sp, SEASON_WINDOWS_8760["spring"])
        summer_part  = _slice_by_1indexed_hours(df_su, SEASON_WINDOWS_8760["summer"])
        autumn_part  = _slice_by_1indexed_hours(df_a,  SEASON_WINDOWS_8760["autumn"])
        winter_part2 = _slice_by_1indexed_hours(df_w,  [(8017, 8760)])

        df = pd.concat([winter_part1, spring_part, summer_part, autumn_part, winter_part2], ignore_index=True)

        if len(df) != 8760:
            raise ValueError(f"Stitched profile has {len(df)} rows, expected 8760.")

    else:
        raise ValueError("calculation_type must be 'annual' or 'seasonal'.")

    P_kW_series = pd.to_numeric(df["electricity"], errors="coerce").fillna(0.0).clip(lower=0.0)

    dt_hours  = _median_dt_hours(df)
    E_gen_kWh = float((P_kW_series * dt_hours).sum())
    if E_gen_kWh <= 0:
        raise ValueError("E_gen_kWh is 0 — check data and units.")

    unit = E_required_unit.strip().lower()
    if unit == "kwh":
        E_req_kWh = E_required
    elif unit == "mwh":
        E_req_kWh = E_required * 1000.0
    elif unit == "gwh":
        E_req_kWh = E_required * 1_000_000.0
    else:
        raise ValueError("E_required_unit must be kWh, MWh, or GWh.")

    if extra_loss_fraction > 0:
        E_req_kWh = E_req_kWh / (1.0 - extra_loss_fraction)

    P_req_kW = cap_kW * (E_req_kWh / E_gen_kWh)
    P_req_MW = P_req_kW / 1000.0

    return {
        "calculation_type"    : calculation_type,
        "reference_capacity_kW": cap_kW,
        "timestep_hours"      : dt_hours,
        "rows_used"           : len(df),
        "E_gen_MWh"           : E_gen_kWh / 1000.0,
        "E_ref_MWh_per_MW"    : E_gen_kWh / cap_kW,
        "P_required_MW"       : P_req_MW,
    }


if __name__ == "__main__":
    base_dir = Path(__file__).parent

    while True:
        calc_type = input("Calculation type (annual / seasonal): ").strip().lower()
        if calc_type in ("annual", "seasonal"):
            break
        print("Enter 'annual' or 'seasonal'.")

    csv_path = base_dir / "annual.csv"
    if calc_type == "annual":
        if not csv_path.exists():
            raise FileNotFoundError(f"Not found: {csv_path}")
        print(f"Using: {csv_path.name}")
    else:
        print("Seasonal mode — will use winter.csv, spring.csv, summer.csv, autumn.csv")

    while True:
        try:
            E_required = float(input("Required annual energy: "))
            break
        except ValueError:
            print("Enter a valid number.")

    while True:
        unit = input("Unit (kWh / MWh / GWh): ").strip().lower()
        if unit in ("kwh", "mwh", "gwh"):
            break
        print("Enter kWh, MWh, or GWh.")

    result = size_pv_from_hourly_kw_ninja(
        str(csv_path),
        E_required,
        E_required_unit=unit,
        calculation_type=calc_type,
    )

    print("\n----- Results -----")
    for k, v in result.items():
        print(f"{k}: {v}")
