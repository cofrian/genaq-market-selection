"""Final scoring model: rank Spain's census sections and return the top 50.

Joins four levels of geography onto each census section --
  section    -> household income, demographic fit
  municipal  -> water quality, drought pressure, machine yield   (CPRO+CMUN)
  regional   -> bottled-water demand, water stress               (CODAUTO)
-- then applies the weights in `config.WEIGHTS`.

Run with:  python -m src.modelo
"""
from __future__ import annotations

import argparse

import pandas as pd

from src.config import (CCAA_WEIGHTS, DATA_PROCESSED, RESULTS, TOP_N, WEIGHTS)

MUNICIPAL_KEYS = ["CPRO", "CMUN"]


def minmax(s: pd.Series) -> pd.Series:
    """Scale to [0, 1]. A constant column maps to 0.0 rather than dividing by zero."""
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or hi == lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def cargar_datos() -> dict[str, pd.DataFrame]:
    """Read the processed tables. Fails loudly if the pipeline hasn't been run."""
    paths = {
        "secciones": DATA_PROCESSED / "secciones_renta_poblacion.csv",
        "municipios": DATA_PROCESSED / "municipios_generacion_calidad.csv",
        "sequia": DATA_PROCESSED / "municipios_sequia.csv",
        "ccaa": DATA_PROCESSED / "ccaa_indicadores.csv",
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing processed data:\n  " + "\n  ".join(missing)
            + "\nSee data/README.md for how to obtain or rebuild it."
        )
    # `seccion_censal` is an identifier, not a number: read as int it would drop
    # the leading zero of provinces 01-09.
    return {k: pd.read_csv(p, dtype={"seccion_censal": str}) for k, p in paths.items()}


def puntuacion_ccaa(ccaa: pd.DataFrame) -> pd.DataFrame:
    """Regional composite.

    Bottled-water demand and the non-potable share are scaled by regional
    population -- a thirsty region with few people is a small market -- while
    water stress enters on its own, since it describes the supply side
    regardless of how many people live there.
    """
    ccaa = ccaa.copy()
    ccaa["otros_datos_ccaa"] = (
        ccaa["poblacion_norm"]
        * (
            CCAA_WEIGHTS["consumo_embotellada"] * ccaa["consumo_embotellada_norm"]
            + CCAA_WEIGHTS["agua_no_potable"] * ccaa["agua_no_potable_norm"]
        )
        + CCAA_WEIGHTS["estres_hidrico"] * ccaa["estres_hidrico"]
    )
    ccaa["ccaa_norm"] = minmax(ccaa["otros_datos_ccaa"])
    return ccaa[["CODAUTO", "ccaa", "otros_datos_ccaa", "ccaa_norm"]]


def construir_tabla(datos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join every indicator onto the census sections."""
    secciones = datos["secciones"]

    municipios = datos["municipios"][
        MUNICIPAL_KEYS + ["generacion_norm", "no_potabilidad"]
    ].drop_duplicates(MUNICIPAL_KEYS)

    sequia = datos["sequia"][MUNICIPAL_KEYS + ["puntuacion_sequia"]].drop_duplicates(
        MUNICIPAL_KEYS
    )

    df = (
        secciones.merge(municipios, on=MUNICIPAL_KEYS, how="left")
        .merge(sequia, on=MUNICIPAL_KEYS, how="left")
        .merge(puntuacion_ccaa(datos["ccaa"]), on="CODAUTO", how="left")
    )

    # `puntuacion_sequia` is unbounded (a station-risk score times a
    # distance-weighted reservoir average), so it needs scaling like the rest.
    df["sequia_norm"] = minmax(df["puntuacion_sequia"])
    df["no_potabilidad_norm"] = df["no_potabilidad"] / 100.0

    # ~7% of sections sit in municipalities with no nearby gauged station or
    # reservoir. Dropping them would silently shrink the candidate pool, so they
    # take their region's median drought score and are flagged. See README.
    df["sequia_imputada"] = df["sequia_norm"].isna()
    df["sequia_norm"] = df["sequia_norm"].fillna(
        df.groupby("CODAUTO")["sequia_norm"].transform("median")
    )
    df["sequia_norm"] = df["sequia_norm"].fillna(df["sequia_norm"].median())
    return df


def calcular_puntuacion(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the weighted sum. Weights and columns are matched by name."""
    df = df.copy()
    faltantes = [c for c in WEIGHTS if c not in df.columns]
    if faltantes:
        raise KeyError(f"Columns required by the model are missing: {faltantes}")

    df["puntuacion_final"] = sum(peso * df[col] for col, peso in WEIGHTS.items())
    return df.sort_values("puntuacion_final", ascending=False).reset_index(drop=True)


def main(top_n: int = TOP_N) -> pd.DataFrame:
    df = calcular_puntuacion(construir_tabla(cargar_datos()))

    RESULTS.mkdir(parents=True, exist_ok=True)
    columnas = [
        "seccion_censal", "municipio", "ccaa", "CPRO", "CMUN", "CODAUTO",
        "longitud", "latitud", *WEIGHTS.keys(), "sequia_imputada", "puntuacion_final",
    ]
    df[columnas].to_csv(RESULTS / "ranking_secciones.csv", index=False, encoding="utf-8")
    top = df[columnas].head(top_n)
    top.to_csv(RESULTS / f"top_{top_n}_secciones.csv", index=False, encoding="utf-8")

    print(f"Scored {len(df):,} census sections "
          f"({df['sequia_imputada'].sum():,} with an imputed drought score).")
    print(f"Wrote results/ranking_secciones.csv and results/top_{top_n}_secciones.csv\n")
    print(f"Top 10 of {top_n}:")
    print(top[["seccion_censal", "municipio", "ccaa", "puntuacion_final"]]
          .head(10).to_string(index=False))
    return top


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=TOP_N,
                        help=f"how many sections to export (default: {TOP_N})")
    main(parser.parse_args().top)
