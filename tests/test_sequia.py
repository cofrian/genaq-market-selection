import numpy as np
import pandas as pd
import pytest

from src.sequia import (_zona, asociar_embalses, asociar_estaciones,
                        puntuacion_sequia, riesgo_estaciones_municipio,
                        riesgo_por_embalse, riesgo_por_estacion,
                        sequia_embalses_municipio)


class TestRiesgoPorEmbalse:
    def test_riesgo_es_uno_menos_el_llenado(self):
        df = pd.DataFrame({
            "embalse_nombre": ["A", "A"],
            "fecha": pd.to_datetime(["2020-01-01", "2020-06-01"]),
            "agua_actual": [30.0, 50.0],
            "agua_total": [100.0, 100.0],
        })
        assert riesgo_por_embalse(df)["riesgo_sequia"].iloc[0] == pytest.approx(0.6)

    def test_promedia_por_anio_antes_que_global(self):
        """2020 is sampled twice and 2021 once; each year must weigh the same."""
        df = pd.DataFrame({
            "embalse_nombre": ["A"] * 3,
            "fecha": pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01"]),
            "agua_actual": [0.0, 100.0, 0.0],   # 2020 -> 50, 2021 -> 0  => mean 25
            "agua_total": [100.0] * 3,
        })
        assert riesgo_por_embalse(df)["riesgo_sequia"].iloc[0] == pytest.approx(0.75)


class TestRiesgoPorEstacion:
    def _estaciones(self, filas):
        return pd.DataFrame(filas)

    def test_estacion_sin_sequia_puntua_cero(self):
        df = self._estaciones([{"Estaciones": "seca", "6": -2.0, "12": -2.0, "24": -2.0},
                               {"Estaciones": "humeda", "6": 1.0, "12": 1.0, "24": 1.0}])
        out = riesgo_por_estacion(df).set_index("Estaciones")
        assert out.at["humeda", "riesgo_psi_norm"] == 0.0
        assert out.at["seca", "riesgo_psi_norm"] > 0

    def test_spi_por_encima_de_menos_uno_no_cuenta(self):
        df = self._estaciones([{"Estaciones": "a", "6": -0.99, "12": -0.5, "24": 0.0},
                               {"Estaciones": "b", "6": -1.01, "12": -0.5, "24": 0.0}])
        out = riesgo_por_estacion(df).set_index("Estaciones")
        assert out.at["a", "riesgo_total"] == 0.0
        assert out.at["b", "riesgo_total"] > 0

    def test_escalas_largas_pesan_mas(self):
        """The same deficit at 24 months must outscore one at 6 months."""
        df = self._estaciones([{"Estaciones": "corta", "6": -2.0, "12": 0.0, "24": 0.0},
                               {"Estaciones": "larga", "6": 0.0, "12": 0.0, "24": -2.0}])
        out = riesgo_por_estacion(df).set_index("Estaciones")
        assert out.at["larga", "riesgo_total"] > out.at["corta", "riesgo_total"]

    def test_normalizado_se_recorta_a_cien(self):
        df = self._estaciones(
            [{"Estaciones": f"e{i}", "6": -1.1, "12": -1.1, "24": -1.1} for i in range(20)]
            + [{"Estaciones": "extrema", "6": -5.0, "12": -5.0, "24": -5.0}]
        )
        assert riesgo_por_estacion(df)["riesgo_psi_norm"].max() == 100.0


class TestZonas:
    def test_detecta_canarias(self):
        assert _zona(28.1, -15.4) == "islas_canarias"

    def test_detecta_baleares(self):
        assert _zona(39.6, 2.9) == "islas_baleares"

    def test_peninsula_por_defecto(self):
        assert _zona(40.4, -3.7) == "peninsula"


class TestAsociarEmbalses:
    def test_encuentra_el_embalse_cercano(self):
        municipios = pd.DataFrame([{"municipio": "X", "lat": 40.0, "lon": -3.7}])
        embalses = pd.DataFrame([{"nombre_embalse": "cerca", "lat": 40.1, "lon": -3.7}])
        out = asociar_embalses(municipios, embalses, radios_km=[50])
        assert out["total_embalses"].iloc[0] == 1
        assert out["embalses"].iloc[0][0]["embalse"] == "cerca"

    def test_ignora_lo_que_queda_fuera_del_radio(self):
        municipios = pd.DataFrame([{"municipio": "X", "lat": 40.0, "lon": -3.7}])
        embalses = pd.DataFrame([{"nombre_embalse": "lejos", "lat": 43.0, "lon": -3.7}])
        out = asociar_embalses(municipios, embalses, radios_km=[50])
        assert out["total_embalses"].iloc[0] == 0
        assert out["radio_km"].iloc[0] is None

    def test_amplia_el_radio_solo_si_hace_falta(self):
        municipios = pd.DataFrame([{"municipio": "X", "lat": 40.0, "lon": -3.7}])
        embalses = pd.DataFrame([{"nombre_embalse": "a 80km", "lat": 40.72, "lon": -3.7}])
        out = asociar_embalses(municipios, embalses, radios_km=[50, 100])
        assert out["radio_km"].iloc[0] == 100

    def test_una_isla_nunca_coge_un_embalse_peninsular(self):
        """Straight-line distance would happily cross the sea; zones must stop it."""
        municipios = pd.DataFrame([{"municipio": "Ibiza", "lat": 38.9, "lon": 1.4}])
        embalses = pd.DataFrame([{"nombre_embalse": "peninsular", "lat": 38.9, "lon": 0.1}])
        out = asociar_embalses(municipios, embalses, radios_km=[160])
        assert out["total_embalses"].iloc[0] == 0


class TestCombinacion:
    def test_estacion_homonima_pesa_mas(self):
        fila = {"municipio": "Burgos",
                "estaciones_cercanas": [{"Estaciones": "Burgos", "riesgo_psi_norm": 100.0},
                                        {"Estaciones": "Soria", "riesgo_psi_norm": 0.0}]}
        assert riesgo_estaciones_municipio(fila) == pytest.approx(65.0)

    def test_sin_homonima_promedia(self):
        fila = {"municipio": "Cuenca",
                "estaciones_cercanas": [{"Estaciones": "Soria", "riesgo_psi_norm": 100.0},
                                        {"Estaciones": "Teruel", "riesgo_psi_norm": 0.0}]}
        assert riesgo_estaciones_municipio(fila) == pytest.approx(50.0)

    def test_sin_estaciones_devuelve_none(self):
        assert riesgo_estaciones_municipio({"municipio": "X", "estaciones_cercanas": []}) is None

    def test_embalses_pondera_por_distancia(self):
        embalses = [{"embalse": "cerca", "distancia_km": 10.0},
                    {"embalse": "lejos", "distancia_km": 100.0}]
        out = sequia_embalses_municipio(embalses, {"cerca": 1.0, "lejos": 1.0})
        assert out == pytest.approx(np.mean([1 / 10, 1 / 100]))

    def test_embalse_a_distancia_cero_no_rompe(self):
        assert np.isnan(sequia_embalses_municipio([{"embalse": "a", "distancia_km": 0.0}], {"a": 1.0}))

    def test_sin_embalses_la_puntuacion_es_la_de_estaciones(self):
        assert puntuacion_sequia(42.0, np.nan) == 42.0

    def test_con_embalses_se_multiplica(self):
        assert puntuacion_sequia(50.0, 2.0) == pytest.approx(100.0)


class TestAsociarEstaciones:
    def test_coge_las_n_mas_cercanas(self):
        municipios = pd.DataFrame([{"municipio": "X", "lat": 40.0, "lon": -3.7}])
        estaciones = pd.DataFrame([
            {"Estaciones": "cerca", "lat": 40.1, "lon": -3.7, "riesgo_psi_norm": 10.0},
            {"Estaciones": "media", "lat": 41.0, "lon": -3.7, "riesgo_psi_norm": 20.0},
            {"Estaciones": "lejos", "lat": 43.0, "lon": -3.7, "riesgo_psi_norm": 30.0},
        ])
        out = asociar_estaciones(municipios, estaciones, n=2)
        nombres = [e["Estaciones"] for e in out["estaciones_cercanas"].iloc[0]]
        assert nombres == ["cerca", "media"]
