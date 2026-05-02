# finalYearProject
# Technical and Economic Assessment of Solar PV Penetration from an Energy Retailer Perspective

## Introduction

This repository contains the Python code used for the technical, economic, and sensitivity analysis in my final-year project on solar photovoltaic (PV) penetration from an energy retailer perspective.

The project evaluates how increasing PV penetration affects hourly demand–generation interaction, imports, exports, self-supplied energy, avoided procurement, and investment value under a planning-level analytical framework. The code is organised into three main scripts:

- `capacityScenario.py`
- `residual_section_34.py`
- `sensitivity_variable_price.py`

Together, these scripts implement PV capacity sizing, hourly demand–generation balancing, and fixed-price versus variable-price sensitivity analysis.

## How to Run the Code

### 1. `capacityScenario.py`

This script is used to size the installed PV capacity required to meet a chosen annual energy target. It supports both annual and seasonal calculation modes.

The script reads Renewables.ninja output, extracts the reference capacity, calculates the annual reference yield, and returns the installed PV capacity required for the chosen energy requirement.

Expected input files:
- `annual.csv` for annual mode
- `winter.csv`, `spring.csv`, `summer.csv`, `autumn.csv` for seasonal mode

### 2. `residual_section_34.py`

This script performs the hourly technical analysis used for the main demand–generation balance.

It:
- reads and resamples Gridwatch demand data to hourly resolution
- builds the reference PV generation profile
- scales the PV profile to the required installed capacity
- aligns hourly PV generation with hourly demand
- calculates residual demand, imports, exports, and self-supply

Expected input files:
- `annual.csv` or seasonal PV files
- `gridwatch.csv`

Main outputs:
- hourly residual-demand results
- annual summary values for demand, PV generation, imports, exports, and self-supply


### 4. `sensitivity_variable_price.py`

This script performs the electricity-pricing sensitivity analysis.

It:
- imports the hourly technical results from `residual_section_34.py`
- loads and merges weekly market index price files
- filters prices to the APXMIDP provider
- compares a fixed-price case and a variable-price case
- calculates annual avoided procurement, procurement cost, CAPEX, and NPV
- generates NPV results across multiple project-life values

The script currently uses these planning-level assumptions:
- fixed price = £93.4393/MWh
- export price = £0/MWh
- CAPEX = £462,000/MW
- discount rate = 5%
- project life = 35 years

Main outputs:
- `sensitivity_results.csv`
- `sensitivity_results_by_project_life.csv`

## More Technical Details

### PV Capacity Sizing

The installed PV capacity is sized by first calculating the annual reference energy yield of a reference PV system, then scaling capacity according to the required annual energy target.

### Residual Demand Framework

The hourly PV generation profile is aligned with hourly demand to calculate:
- residual demand
- imports
- exports
- self-supplied PV generation

This provides the technical basis for the later economic and investment analysis.

### Economic and Investment Analysis

The repository includes both a fixed-price and variable-price valuation of self-supplied electricity. The variable-price script values self-supply using hourly market prices and compares the resulting annual benefits and net present values with the fixed-price case.

## Repository Structure

- `capacityScenario.py` – PV capacity sizing
- `residual_section_34.py` – hourly technical balance
- `sensitivity_variable_price.py` – pricing sensitivity and NPV analysis

## Known Issues / Future Improvements

- Some file paths are hard-coded and may need to be updated for a different machine
- The scripts currently rely on CSV files being placed in expected locations
- Error handling could be improved for inconsistent file formats
- The framework is planning-level and does not model network-constrained power flow, storage dispatch, or market-clearing behaviour
- Future improvements could include cleaner configuration handling, automatic plotting, and extension to storage or demand-side response analysis
