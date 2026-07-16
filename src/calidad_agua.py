"""Tap-water quality -> a per-municipality `no_potabilidad` score (0-100).

Input is SINAC's national drinking-water register (one row per parameter, per
sample, per network). The chain is:

    raw samples -> one dict of {parameter: value} per sample
                -> each parameter checked against its legal limit (RD 3/2023)
                -> per-municipality aggregate -> `no_potabilidad`

A high score means the tap water is hard, off-pH or frequently out of spec --
which is what makes a household a good prospect for an atmospheric generator.

Requires the raw SINAC export; see data/README.md.
"""
from __future__ import annotations

import ast

import numpy as np
import pandas as pd

# Legal limits, RD 3/2023 (previously RD 140/2003). A tuple is an allowed range,
# a scalar is an upper bound. Parameters absent here are ignored, not failed.
LIMITES_PARAMETROS: dict[str, float | tuple[float, float]] = {
    # microbiological -- any presence is a failure
    "Escherichia coli": 0,
    "Bacterias coliformes": 0,
    "Enterococo": 0,
    "Clostridium perfringens (incluidas las esporas)": 0,
    "Colifagos somáticos": 0,
    "Legionella spp": 0,
    "Recuento de colonias a 22ºC": 100,
    # organoleptic / physico-chemical
    "PH": (6.5, 9.5),
    "Conductividad": 2500,
    "Turbidez": 6,
    "Color": 15,
    "Olor": 3,
    "Sabor": 3,
    "Dureza Total (CaCO3)": (150, 500),
    "Indice de Langelier": (-0.5, 0.5),
    "Oxidabilidad": 5,
    "Carbono Orgánico total": 2,
    "Amonio": 0.5,
    "Cloro libre residual": 1,
    "Cloro combinado residual": 2,
    # ions and metals
    "Aluminio": 200,
    "Hierro": 200,
    "Manganeso": 50,
    "Cloruro": 250,
    "Sulfato": 250,
    "Sodio": 200,
    "Potasio": 12,
    "Calcio": 100,
    "Magnesio": 50,
    "Cobre": 2000,
    "Cromo total": 50,
    "Níquel": 20,
    "Selenio": 10,
    "Boro": 1,
    "Fluoruro": 1.5,
    "Arsénico": 10,
    "Plomo": 10,
    "Cadmio": 5,
    "Mercurio": 1,
    "Antimonio": 5,
    "Cianuro total": 50,
    # nutrients and by-products
    "Nitrato": 50,
    "Nitritos": 0.5,
    "Bromato": 10,
    "Suma 4 Trihalometanos (THM)": 100,
    "Suma 2 Tricloroeteno + Tetracloroeteno": 10,
    "Suma 4 Hidrocarburos Policíclicos Aromáticos (HPA)": 0.1,
    "Benzo(a)pireno (CAS 50-32-8)": 0.01,
    "Benceno (CAS 71-43-2)": 1,
    "1,2-Dicloroetano (CAS 107-06-2)": 3,
    "Cloruro de Vinilo (CAS 75-01-4)": 0.5,
    "Suma total Plaguicidas": 0.5,
    # radiological
    "Radon": 100,
    "Tritio": 100,
    "Actividad a total": 0.1,
    "Actividad b resto": 1,
    "Dosis Indicativa (Suma radionucleidos) DI": 0.1,
}

COLUMNAS_SINAC = [
    "Comunidad_Autonoma", "Provincia", "Ciudad", "_id", "Red_Distribucion",
    "Organismo_gestor", "Fecha", "_cod", "Laboratorio", "Clase_de_boletin",
    "Tipo_de_analisis", "Valor_cuantificado", "unidades",
]


def cargar_sinac(path) -> pd.DataFrame:
    """Read and normalise a raw SINAC export (latin-1, ';', comma decimals)."""
    df = pd.read_csv(path, sep=";", encoding="latin1", low_memory=False)
    df.columns = COLUMNAS_SINAC
    df = df.drop(columns=["_id", "_cod", "Red_Distribucion", "Organismo_gestor"])

    df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce").dt.date
    df["Comunidad_Autonoma"] = (
        df["Comunidad_Autonoma"].str.replace(r"\d+", "", regex=True).str.strip()
    )
    df["Ciudad"] = df["Ciudad"].str.strip().str.upper()
    df["Valor_cuantificado"] = pd.to_numeric(
        df["Valor_cuantificado"].astype(str).str.replace(",", "."), errors="coerce"
    )
    return df[df["Tipo_de_analisis"].isin(LIMITES_PARAMETROS)]


def agrupar_por_muestra(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the long parameter rows into one dict per (municipality, date)."""
    agrupado = (
        df.groupby(["Ciudad", "Fecha"])
        .agg(
            Comunidad_Autonoma=("Comunidad_Autonoma", "first"),
            Provincia=("Provincia", "first"),
            parametros=("Tipo_de_analisis", list),
            valores=("Valor_cuantificado", list),
        )
        .reset_index()
    )
    agrupado["Analisis_Valor"] = [
        dict(zip(p, v)) for p, v in zip(agrupado["parametros"], agrupado["valores"])
    ]
    return agrupado.drop(columns=["parametros", "valores"])


def evaluar_muestra(analisis: dict | str) -> dict[str, bool]:
    """Check each measured parameter against its limit. True == within spec."""
    if isinstance(analisis, str):
        analisis = ast.literal_eval(analisis)

    resultado = {}
    for parametro, valor in analisis.items():
        limite = LIMITES_PARAMETROS.get(parametro)
        if limite is None:
            continue
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            continue  # non-numeric (qualitative) reading: no verdict
        resultado[parametro] = (
            limite[0] <= valor <= limite[1] if isinstance(limite, tuple) else valor <= limite
        )
    return resultado


def evaluar_muestras(df: pd.DataFrame) -> pd.DataFrame:
    """Per sample: which parameters passed, how many, and whether all did."""
    df = df.copy()
    veredictos = df["Analisis_Valor"].apply(evaluar_muestra)

    df["pH"] = df["Analisis_Valor"].apply(lambda d: pd.to_numeric(d.get("PH"), errors="coerce"))
    df["dureza"] = df["Analisis_Valor"].apply(
        lambda d: pd.to_numeric(d.get("Dureza Total (CaCO3)"), errors="coerce")
    )
    df["valores_true"] = veredictos.apply(lambda d: sum(d.values()))
    df["valores_false"] = veredictos.apply(lambda d: len(d) - sum(d.values()))
    # A sample with no gradeable parameter is not "potable", it's unknown.
    df["potable"] = veredictos.apply(lambda d: bool(d) and all(d.values()))
    return df


def agrupar_por_municipio(df: pd.DataFrame) -> pd.DataFrame:
    agrupado = (
        df.groupby("Ciudad")
        .agg(
            ccaa=("Comunidad_Autonoma", "first"),
            provincia=("Provincia", "first"),
            ph_medio=("pH", "mean"),
            dureza_media=("dureza", "mean"),
            parametros_ok=("valores_true", "sum"),
            parametros_fuera_rango=("valores_false", "sum"),
            n_muestras=("Fecha", "count"),
            n_potable=("potable", "sum"),
        )
        .reset_index()
        .rename(columns={"Ciudad": "municipio"})
    )
    return agrupado


def calcular_no_potabilidad(df: pd.DataFrame) -> pd.Series:
    """Score how *unsuitable* a municipality's tap water is, 0-100.

    Three penalties, weighted 65/20/15:
      * hardness  -- the main driver of bottled-water habits. Water inside
                     150-500 mg/L CaCO3 is unpenalised; above 500 the penalty
                     saturates exponentially, below 150 it grows linearly.
      * pH        -- quadratic penalty once outside 6.5-9.5, scaled by the
                     worst deviation observed nationally.
      * failures  -- share of readings out of spec, amplified by log1p(n) so a
                     town failing across many samples outranks one bad test.
    """
    # Index into the branches rather than np.select, which would evaluate exp()
    # on the NaN rows too. Missing readings stay unpenalised.
    dureza = pd.to_numeric(df["dureza_media"], errors="coerce").to_numpy(dtype=float)
    penal_dureza = np.zeros(len(df))
    alta, baja = dureza > 500, dureza < 150          # NaN compares False on both
    penal_dureza[alta] = 1 - np.exp(-(dureza[alta] - 500) / 100)
    penal_dureza[baja] = (150 - dureza[baja]) / 300

    ph = pd.to_numeric(df["ph_medio"], errors="coerce").to_numpy(dtype=float)
    desviacion = np.zeros(len(df))
    acido, basico = ph < 6.5, ph > 9.5
    desviacion[acido] = (6.5 - ph[acido]) ** 2
    desviacion[basico] = (ph[basico] - 9.5) ** 2

    escala_ph = max(np.nanmax(ph) - 9.5, 6.5 - np.nanmin(ph)) ** 2 if np.isfinite(ph).any() else 0.0
    penal_ph = desviacion / escala_ph if escala_ph > 0 else np.zeros(len(df))

    total = df["parametros_ok"] + df["parametros_fuera_rango"]
    penal_fallos = np.where(
        total > 0, (df["parametros_fuera_rango"] / total) * np.log1p(total), 0.0
    )

    score = 0.65 * penal_dureza + 0.20 * penal_ph + 0.15 * penal_fallos
    return pd.Series(np.clip(score * 100, 0, 100), index=df.index)


def procesar(path_sinac) -> pd.DataFrame:
    """Full chain: raw SINAC export -> per-municipality quality table."""
    muestras = evaluar_muestras(agrupar_por_muestra(cargar_sinac(path_sinac)))
    municipios = agrupar_por_municipio(muestras)
    municipios["no_potabilidad"] = calcular_no_potabilidad(municipios)
    return municipios.sort_values("no_potabilidad", ascending=False)
