"""Project-wide paths, constants and the scoring weights.

Everything that a reader might want to tweak lives here, so no module needs to
hardcode a path or a magic number.
"""
from pathlib import Path

# --------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
RESULTS = ROOT / "results"

# --------------------------------------------------- final model weights
# Weights of the section-level score. They sum to 1.0 (asserted below).
# Rationale for the ordering is in README.md > "The scoring model".
WEIGHTS = {
    "generacion_norm": 0.1000,        # litres/day the unit yields in that climate
    "sequia_norm": 0.1325,            # drought pressure (reservoirs + SPI stations)
    "no_potabilidad_norm": 0.2125,    # tap water quality, worse = better prospect
    "poblacion_ideal_norm": 0.1600,   # demographic fit of the census section
    "renta_hogar_norm": 0.1700,       # household income (ability to pay)
    "ccaa_norm": 0.2250,              # regional water context (bottled use, stress)
}

# Regional composite (`ccaa_norm` before normalisation).
# population-weighted bottled-water demand + non-potable share, plus water stress.
CCAA_WEIGHTS = {
    "consumo_embotellada": 0.550,
    "agua_no_potable": 0.225,
    "estres_hidrico": 0.225,
}

TOP_N = 50  # census sections to hand to the sales team

# ---------------------------------------------- drought scoring (SPI/PSI)
# Weights per SPI timescale: a 24-month deficit signals structural drought,
# a 6-month one is closer to seasonal noise, so longer windows weigh more.
SPI_CONFIG = {
    "escalas_temporales": {"24": 10, "12": 5, "6": 2},
    "peso_deficit": 1,
    "peso_intensidad": 12,
    "peso_duracion": 3,
    "umbrales_intensidad": [-1.0, -1.5, -2.0],
    "multiplicadores_intensidad": [1, 2, 3],
    "percentil_normalizacion": 95,
    # The 2025 submission never applied the x2/x3 multipliers: its loop broke at
    # the first threshold (-1.0), which every drought SPI clears by definition,
    # so intensity was always x1 and the escalation was unreachable code.
    # False  -> keep that behaviour, reproducing the committed processed data.
    # True   -> the escalation as intended; moves 68 of 85 stations.
    # See README > "A bug worth keeping".
    "escalada_intensidad": False,
}

# Radii (km) tried in order when linking a municipality to its reservoirs.
# Each pass only covers municipalities the previous radius left unmatched.
RADIOS_EMBALSES_KM = [50, 75, 100, 160]

# Bounding boxes so island municipalities never match a mainland reservoir.
ZONAS_ESPECIALES = {
    "islas_canarias": {"lat_min": 27.0, "lat_max": 29.5, "lon_min": -18.5, "lon_max": -13.0},
    "islas_baleares": {"lat_min": 38.5, "lat_max": 40.5, "lon_min": 1.0, "lon_max": 5.0},
    "ceuta_melilla": {"lat_min": 35.0, "lat_max": 36.0, "lon_min": -5.5, "lon_max": -2.5},
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Model weights must sum to 1.0"
assert abs(sum(CCAA_WEIGHTS.values()) - 1.0) < 1e-9, "CCAA weights must sum to 1.0"
