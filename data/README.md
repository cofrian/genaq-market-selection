# Data

`data/processed/` is committed (~5 MB) and is all you need to run the model.
`data/raw/` is git-ignored: the sources are hundreds of MB and are public
anyway, so this file tells you where to get them instead.

## Committed — `data/processed/`

| File | Rows | Grain | What it holds |
|---|---:|---|---|
| `secciones_renta_poblacion.csv` | 35,891 | census section | Household income 2024 (raw + normalised), demographic fit, coordinates |
| `municipios_generacion_calidad.csv` | 8,124 | municipality | Machine yield (L/day) and `no_potabilidad` |
| `municipios_calidad_agua.csv` | 7,144 | municipality | Measured water quality: mean pH, hardness, pass/fail counts |
| `municipios_sequia.csv` | 8,166 | municipality | Station risk, reservoir stress, combined drought score |
| `ccaa_indicadores.csv` | 19 | region | Bottled-water use, potable access, water stress |

Two row counts deserve a note. `municipios_calidad_agua.csv` has 7,144 rows
because only those municipalities published analyses; the other 1,537 in
`municipios_generacion_calidad.csv` carry a *predicted* `no_potabilidad`
(see README > Limitations). And 8,166 > 8,124 because the drought table keeps
municipalities that later dropped out of the join.

## Not committed — `data/raw/`

| Source | Used for | Where |
|---|---|---|
| Reservoir levels 1988–2025 (weekly, per reservoir) | Reservoir drought risk | [MITECO boletín hidrológico](https://www.miteco.gob.es/es/agua/temas/evaluacion-de-los-recursos-hidricos/boletin-hidrologico.html) |
| SPI drought monitoring, 1–24 month windows per station | Station drought risk | [AEMET vigilancia de la sequía](https://www.aemet.es/es/serviciosclimaticos/vigilancia_clima/vigilancia_sequia) |
| SINAC drinking-water register (national, per sample) | `no_potabilidad` | [SINAC, Ministerio de Sanidad](https://sinac.sanidad.gob.es/) |
| Household income by census section (Atlas de Distribución de Renta) | Ability to pay | [INE ADRH](https://www.ine.es/experimental/atlas/experimental_atlas.htm) |
| Population by age and sex, per census section | Demographic fit | [INE padrón](https://www.ine.es/) |
| Water supply and use survey | Regional water stress | [INE encuesta del agua](https://www.ine.es/) |
| Bottled-water consumption per region | Regional demand | Ministerio de Agricultura, consumption panel |

Filenames and column layouts change between yearly releases, so treat the
loaders in `src/` as written against the 2024–2025 exports.

## Rebuilding `data/processed/`

Geocoding needs a Google Maps key. It is billed per request, so results are
cached to CSV and only new names are queried:

```bash
export GOOGLE_MAPS_API_KEY=...        # PowerShell: $env:GOOGLE_MAPS_API_KEY='...'
python -m src.geocoding --names data/raw/embalses.csv --column embalse_nombre \
                        --out data/raw/coordenadas_embalses.csv --reservoirs
```

`--reservoirs` retries each name with *embalse*, *encoro*, *presa*,
*embassament*, *urtegia* and *pantano*. MITECO names reservoirs in the language
of the basin authority, so "Bao" alone geocodes nowhere useful while "encoro
Bao" lands in Galicia.
