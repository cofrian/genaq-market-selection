"""Drought pressure per municipality, from two independent sources.

  reservoirs -- MITECO's weekly reservoir series (1988-2025). How full is the
                storage a municipality actually draws from, on average?
  SPI/PSI    -- AEMET's Standardised Precipitation Index per weather station,
                across 1-24 month windows. Is rainfall structurally short?

Each municipality is linked to its nearby reservoirs and its two nearest
stations by great-circle distance, then the two signals are combined.

Requires raw MITECO/AEMET files plus geocoded coordinates; see data/README.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src.config import RADIOS_EMBALSES_KM, SPI_CONFIG, ZONAS_ESPECIALES

RADIO_TIERRA_KM = 6371.0


# --------------------------------------------------------------- reservoirs
def cargar_embalses(path) -> pd.DataFrame:
    """Read MITECO's reservoir series and keep 2015 onwards."""
    df = pd.read_csv(path, sep=";", encoding="latin1")
    df.columns = ["ambito_nombre", "embalse_nombre", "fecha", "agua_total",
                  "agua_actual", "electrico"]
    df = df.drop(columns=["electrico"])

    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    for col in ("agua_total", "agua_actual"):
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "."), errors="coerce")

    return df[df["fecha"] >= "2015-01-01"]


def riesgo_por_embalse(df: pd.DataFrame) -> pd.DataFrame:
    """Mean fill ratio per reservoir -> risk = 1 - ratio.

    Averaged per year first, then across years, so that a reservoir reported
    more often in some years doesn't dominate its own average.
    """
    anual = (
        df.assign(year=df["fecha"].dt.year)
        .groupby(["embalse_nombre", "year"])[["agua_actual", "agua_total"]]
        .mean()
        .reset_index()
    )
    medias = anual.groupby("embalse_nombre")[["agua_actual", "agua_total"]].mean().reset_index()
    medias["proporcion_volumen"] = medias["agua_actual"] / medias["agua_total"]
    medias["riesgo_sequia"] = 1 - medias["proporcion_volumen"]
    return medias.sort_values("riesgo_sequia", ascending=False)


# ------------------------------------------------------------- SPI stations
def riesgo_por_estacion(df: pd.DataFrame) -> pd.DataFrame:
    """Turn a station's SPI series into one risk score, normalised to p95.

    Three ingredients, per `config.SPI_CONFIG`:
      deficit    -- sum of |SPI| below -1, weighted by timescale (24m > 12m > 6m)
      intensity  -- the worst SPI, amplified as it crosses -1.0 / -1.5 / -2.0
      duration   -- how many timescales are in drought at once

    Normalising to the 95th percentile rather than the max keeps a single
    freak station from compressing everyone else toward zero; scores are then
    clipped to 100.

    Intensity escalation is gated by `SPI_CONFIG["escalada_intensidad"]`; the
    original never reached it. See config.py and README > "A bug worth keeping".
    """
    escalas = [c for c in df.columns if c.isdigit()]
    pesos = SPI_CONFIG["escalas_temporales"]
    spi = df[escalas].apply(pd.to_numeric, errors="coerce")

    en_sequia = spi <= -1
    peso_escala = np.array([pesos.get(c, 1) for c in escalas])

    deficit = (spi.abs().where(en_sequia, 0) * peso_escala).sum(axis=1)
    duracion = en_sequia.sum(axis=1)

    spi_min = spi.where(en_sequia).min(axis=1)
    intensidad = spi_min.abs().fillna(0.0)
    if SPI_CONFIG["escalada_intensidad"]:
        # Strongest threshold cleared wins, so -2.1 scores x3 and -1.2 scores x1.
        for umbral, mult in zip(SPI_CONFIG["umbrales_intensidad"],
                                SPI_CONFIG["multiplicadores_intensidad"]):
            intensidad = intensidad.mask(spi_min <= umbral, spi_min.abs() * mult)

    total = (
        deficit * SPI_CONFIG["peso_deficit"]
        + intensidad * SPI_CONFIG["peso_intensidad"]
        + duracion * SPI_CONFIG["peso_duracion"]
    )

    p95 = np.percentile(total.dropna(), SPI_CONFIG["percentil_normalizacion"])
    return pd.DataFrame({
        "Estaciones": df["Estaciones"],
        "riesgo_total": total,
        "riesgo_psi_norm": np.clip(total / p95 * 100, 0, 100) if p95 > 0 else 0.0,
    }).sort_values("riesgo_psi_norm", ascending=False)


# ----------------------------------------------------- spatial association
def _zona(lat: float, lon: float) -> str:
    """Which island/enclave bounding box a point falls in, else 'peninsula'."""
    for nombre, b in ZONAS_ESPECIALES.items():
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return nombre
    return "peninsula"


def _kdtree(df: pd.DataFrame) -> cKDTree:
    """KD-tree over unit-sphere xyz, so chord queries approximate great circles."""
    lat, lon = np.radians(df["lat"].to_numpy()), np.radians(df["lon"].to_numpy())
    xyz = np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    return cKDTree(xyz)


def _xyz(lat: float, lon: float) -> np.ndarray:
    lat, lon = np.radians(lat), np.radians(lon)
    return np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def _distancia_km(a_lat, a_lon, b_lat, b_lon) -> float:
    """Haversine distance in km."""
    p1, p2 = np.radians([a_lat, a_lon]), np.radians([b_lat, b_lon])
    dlat, dlon = p2[0] - p1[0], p2[1] - p1[1]
    h = np.sin(dlat / 2) ** 2 + np.cos(p1[0]) * np.cos(p2[0]) * np.sin(dlon / 2) ** 2
    return float(2 * RADIO_TIERRA_KM * np.arcsin(np.sqrt(h)))


def asociar_embalses(municipios: pd.DataFrame, embalses: pd.DataFrame,
                     radios_km=RADIOS_EMBALSES_KM) -> pd.DataFrame:
    """Link each municipality to reservoirs, widening the radius only as needed.

    Both frames need `lat`/`lon`; `embalses` needs `nombre_embalse`. Islands are
    matched only against reservoirs in their own zone -- otherwise a KD-tree
    happily connects Ibiza to the mainland across open sea.

    Returns one row per municipality: the reservoirs found, the radius that
    found them, and how many.
    """
    embalses = embalses.copy()
    embalses["zona"] = [_zona(la, lo) for la, lo in zip(embalses["lat"], embalses["lon"])]

    arboles = {z: (_kdtree(g), g.reset_index(drop=True))
               for z, g in embalses.groupby("zona") if len(g)}

    filas, pendientes = [], municipios.copy()
    for radio in radios_km:
        if pendientes.empty:
            break
        siguiente = []
        for _, m in pendientes.iterrows():
            zona = _zona(m["lat"], m["lon"])
            if zona not in arboles:
                siguiente.append(m)
                continue

            arbol, candidatos = arboles[zona]
            # chord length subtending `radio` km of arc on a unit sphere
            cuerda = 2 * np.sin(radio / (2 * RADIO_TIERRA_KM))
            idx = arbol.query_ball_point(_xyz(m["lat"], m["lon"]), cuerda)

            cercanos = [
                {"embalse": candidatos.at[i, "nombre_embalse"],
                 "distancia_km": round(_distancia_km(m["lat"], m["lon"],
                                                     candidatos.at[i, "lat"],
                                                     candidatos.at[i, "lon"]), 2)}
                for i in idx
            ]
            if cercanos:
                filas.append({**m.to_dict(), "embalses": cercanos,
                              "total_embalses": len(cercanos), "radio_km": radio,
                              "zona": zona})
            else:
                siguiente.append(m)
        pendientes = pd.DataFrame(siguiente)

    for _, m in pendientes.iterrows():  # never matched, even at the widest radius
        filas.append({**m.to_dict(), "embalses": [], "total_embalses": 0,
                      "radio_km": None, "zona": _zona(m["lat"], m["lon"])})

    return pd.DataFrame(filas)


def asociar_estaciones(municipios: pd.DataFrame, estaciones: pd.DataFrame,
                       n: int = 2) -> pd.DataFrame:
    """Attach each municipality's `n` nearest SPI stations."""
    arbol = _kdtree(estaciones)
    estaciones = estaciones.reset_index(drop=True)

    puntos = np.array([_xyz(la, lo) for la, lo in zip(municipios["lat"], municipios["lon"])])
    _, indices = arbol.query(puntos, k=min(n, len(estaciones)))
    indices = np.atleast_2d(indices)

    municipios = municipios.copy()
    municipios["estaciones_cercanas"] = [
        [{"Estaciones": estaciones.at[i, "Estaciones"],
          "riesgo_psi_norm": estaciones.at[i, "riesgo_psi_norm"]} for i in fila]
        for fila in indices
    ]
    return municipios


# ------------------------------------------------------------ combination
def riesgo_estaciones_municipio(row) -> float | None:
    """Blend the nearby stations' risk into one number.

    A station named after the municipality is treated as more representative
    of it (65/35); otherwise the two are averaged evenly.
    """
    estaciones = row["estaciones_cercanas"]
    if not estaciones:
        return None

    nombre = str(row["municipio"]).lower()
    propias = [e["riesgo_psi_norm"] for e in estaciones if nombre in str(e["Estaciones"]).lower().split()]
    ajenas = [e["riesgo_psi_norm"] for e in estaciones if nombre not in str(e["Estaciones"]).lower().split()]

    if len(propias) == 1 and len(ajenas) == 1:
        return 0.65 * propias[0] + 0.35 * ajenas[0]
    valores = propias + ajenas
    return float(np.mean(valores)) if valores else None


def sequia_embalses_municipio(embalses: list[dict], riesgos: dict[str, float]) -> float:
    """Distance-weighted mean of nearby reservoir risk (nearer counts more)."""
    ponderadas = [
        riesgos[e["embalse"]] / e["distancia_km"]
        for e in embalses
        if e["embalse"] in riesgos and e["distancia_km"] > 0 and not pd.isna(riesgos[e["embalse"]])
    ]
    return float(np.mean(ponderadas)) if ponderadas else np.nan


def puntuacion_sequia(riesgo_estaciones: float, sequia_embalses: float) -> float:
    """Station risk, amplified by reservoir stress where reservoirs exist.

    Multiplicative: a region can be rain-poor *and* drawing on empty storage,
    and that compounds. Where no reservoir is linked, station risk stands alone.
    """
    if pd.isna(sequia_embalses):
        return riesgo_estaciones
    return riesgo_estaciones * sequia_embalses
