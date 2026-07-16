"""Geocode reservoirs and weather stations via the Google Maps API.

Reservoirs are the awkward part: MITECO names them in whichever language the
basin authority uses, so "Bao" alone geocodes to nowhere useful while "encoro
Bao" resolves in Galicia. Each name is retried with the regional words for
reservoir before giving up.

Results are cached to CSV -- geocoding is billed per request and the station
and reservoir lists barely change between runs.

    export GOOGLE_MAPS_API_KEY=...       # never hardcode this
    python -m src.geocoding --help
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Spanish, Galician, Catalan and Basque for "reservoir"/"dam".
TERMINOS_EMBALSE = ["embalse", "encoro", "presa", "embassament", "urtegia", "pantano"]


def _api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY is not set.\n"
            "Get a key at https://console.cloud.google.com/google/maps-apis and export it:\n"
            "  export GOOGLE_MAPS_API_KEY=...        (PowerShell: $env:GOOGLE_MAPS_API_KEY='...')"
        )
    return key


def geocodificar(consulta: str, timeout: int = 10) -> tuple[float, float] | tuple[None, None]:
    """Geocode one query string. Returns (lat, lon) or (None, None)."""
    try:
        r = requests.get(
            GEOCODE_URL,
            params={"address": consulta, "key": _api_key(), "region": "es"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        print(f"  request failed for {consulta!r}: {e}")
        return None, None

    if data.get("status") == "OK":
        loc = data["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    if data.get("status") not in {"ZERO_RESULTS", "OK"}:
        # OVER_QUERY_LIMIT / REQUEST_DENIED are worth surfacing, not swallowing
        print(f"  API said {data.get('status')} for {consulta!r}: {data.get('error_message', '')}")
    return None, None


def geocodificar_embalse(nombre: str, pausa: float = 0.1) -> tuple[float | None, float | None]:
    """Try a reservoir name with each regional term until one resolves."""
    for termino in TERMINOS_EMBALSE:
        lat, lon = geocodificar(f"{termino} {nombre}, España")
        if lat is not None:
            return lat, lon
        time.sleep(pausa)
    return None, None


def geocodificar_lista(nombres: list[str], cache: Path, es_embalse: bool = False,
                       pausa: float = 0.1) -> pd.DataFrame:
    """Geocode `nombres`, reusing `cache` and only querying what's new."""
    cache = Path(cache)
    hecho = pd.read_csv(cache) if cache.exists() else pd.DataFrame(columns=["nombre", "lat", "lon"])
    pendientes = [n for n in nombres if n not in set(hecho["nombre"])]

    if not pendientes:
        print(f"All {len(nombres)} names already cached in {cache.name}.")
        return hecho

    print(f"Geocoding {len(pendientes)} new names ({len(hecho)} cached)...")
    filas = []
    for i, nombre in enumerate(pendientes, 1):
        lat, lon = (geocodificar_embalse(nombre, pausa) if es_embalse
                    else geocodificar(f"{nombre}, España"))
        if lat is None:
            print(f"  [{i}/{len(pendientes)}] no match: {nombre}")
        filas.append({"nombre": nombre, "lat": lat, "lon": lon})
        time.sleep(pausa)

    resultado = pd.concat([hecho, pd.DataFrame(filas)], ignore_index=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(cache, index=False, encoding="utf-8")

    fallidos = resultado["lat"].isna().sum()
    print(f"Wrote {cache} ({len(resultado)} rows, {fallidos} unresolved).")
    return resultado


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--names", required=True, help="CSV with the names to geocode")
    p.add_argument("--column", required=True, help="column holding the names")
    p.add_argument("--out", required=True, help="cache CSV to write/extend")
    p.add_argument("--reservoirs", action="store_true",
                   help="retry each name with regional words for 'reservoir'")
    args = p.parse_args()

    nombres = pd.read_csv(args.names)[args.column].dropna().unique().tolist()
    geocodificar_lista(nombres, Path(args.out), es_embalse=args.reservoirs)
