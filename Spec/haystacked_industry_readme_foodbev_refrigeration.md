# haystacked Industry Context: Food & Beverage Refrigeration

This document provides domain knowledge for LLM-based tender analysis in the Industrial Refrigeration sector.

## Scope

Industrial refrigeration systems for food & beverage applications. Three sub-types based on temperature zone:

- **Process Cooling** (+2°C to +15°C): Cools process media (glycol circuits, milk, fermentation tanks, brewery wort, process water) during production. Glycol or direct-expansion circuits common.
- **Cold Store** (0°C to +8°C): Maintains refrigerated rooms or warehouses for fresh product storage (fresh produce, dairy, meat). Continuous steady-state operation.
- **Deep Freeze** (−18°C to −40°C): Freezes or stores frozen products. Includes blast freezers (Schockfroster) for rapid pulldown and deep-freeze warehouses.

## Core Components

- **Compressor units**: piston, screw, or scroll; single-stage or two-stage for low temperatures
- **Evaporator/air cooler units**: mounted in cold rooms or process circuits
- **Condenser units**: air-cooled or water-cooled
- **Control system**: monitoring, defrost cycles, alarm management

## Refrigerants

- **R717 (Ammonia / NH3)**: Highest COP, toxic, requires PED certification. Standard for large industrial systems.
- **R744 (CO2 / Transcritical)**: Non-toxic, low GWP, used in cascade or transcritical booster systems for cold store and deep freeze.
- **R290 (Propane)**: Natural refrigerant, flammable (ATEX), small systems.
- **R134a / R32 / R404A / R452A**: HFC/HFO synthetics; F-Gas regulation compliance required.

## Key Performance Parameters

- **Cooling capacity (kW)**: Net cooling power at defined evaporating/condensing temperature. NOT compressor shaft power.
- **COP (Coefficient of Performance)**: Cooling capacity / electrical input power. Higher = better. Typical: 2–6 for cold store; lower for deep freeze.
- **Evaporating temperature (Verdampfungstemperatur)**: Temperature at which refrigerant evaporates. 5–10 K below room target.
- **Condensing temperature (Verflüssigungstemperatur)**: Typically 35–45°C (air-cooled) or 30–40°C (water-cooled).
- **Pulldown time (h)**: Time to cool room from ambient to target temperature.
- **Temperature stability (±K)**: Allowed fluctuation around setpoint. Cold store: ±1K; deep freeze: ±0.5K.

## Standards & Certifications

- **EN 378**: Safety and environmental requirements for refrigerating systems (EU).
- **PED 2014/68/EU**: Pressure Equipment Directive — mandatory for systems above Category I.
- **ATEX**: Required for flammable refrigerants (R290, R717) in explosive atmospheres.
- **F-Gas Regulation (EU 517/2014)**: Limits HFC use; certification required for service personnel.

## Blank ≠ Zero

A null value means the specification is unknown — never that the capability is absent. A supplier with null cooling_capacity_kw may still qualify; do not assume limitation.

## Common Terminology (DE/EN)

| German | English |
|---|---|
| Kälteanlage / Kältetechnik | Refrigeration system |
| Kühllager / Kühlhaus | Cold store |
| Tiefkühlanlage | Deep-freeze system |
| Schockfroster / Schnellfroster | Blast freezer |
| Prozesskühlung | Process cooling |
| Kältemittel | Refrigerant |
| Verdampfer | Evaporator |
| Verflüssiger | Condenser |
| Kälteleistung | Cooling capacity |
| Kältemittelkreislauf | Refrigerant circuit |
| Glykol-Kreislauf | Glycol circuit |
