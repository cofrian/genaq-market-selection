import pandas as pd
import pytest

from src.config import CCAA_WEIGHTS, WEIGHTS
from src.modelo import calcular_puntuacion, construir_tabla, minmax, puntuacion_ccaa


def test_pesos_suman_uno():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(CCAA_WEIGHTS.values()) == pytest.approx(1.0)


def test_minmax_escala_a_cero_uno():
    out = minmax(pd.Series([10.0, 20.0, 30.0]))
    assert out.tolist() == [0.0, 0.5, 1.0]


def test_minmax_columna_constante_no_divide_por_cero():
    assert minmax(pd.Series([7.0, 7.0, 7.0])).tolist() == [0.0, 0.0, 0.0]


def test_minmax_ignora_nan():
    out = minmax(pd.Series([0.0, None, 10.0]))
    assert out[0] == 0.0 and out[2] == 1.0
    assert pd.isna(out[1])


def test_puntuacion_maxima_es_uno():
    """A section that maxes out every normalised driver must score exactly 1.0."""
    fila = pd.DataFrame([{c: 1.0 for c in WEIGHTS}])
    assert calcular_puntuacion(fila)["puntuacion_final"].iloc[0] == pytest.approx(1.0)


def test_puntuacion_minima_es_cero():
    fila = pd.DataFrame([{c: 0.0 for c in WEIGHTS}])
    assert calcular_puntuacion(fila)["puntuacion_final"].iloc[0] == pytest.approx(0.0)


def test_puntuacion_ordena_descendente():
    df = pd.DataFrame([{c: v for c in WEIGHTS} for v in (0.1, 0.9, 0.5)])
    out = calcular_puntuacion(df)["puntuacion_final"]
    assert out.is_monotonic_decreasing


def test_falta_una_columna_falla_ruidosamente():
    df = pd.DataFrame([{c: 1.0 for c in list(WEIGHTS)[:-1]}])
    with pytest.raises(KeyError):
        calcular_puntuacion(df)


def test_ccaa_estres_hidrico_no_escala_con_poblacion():
    """Water stress must enter on its own: an empty region still scores it."""
    ccaa = pd.DataFrame([
        {"CODAUTO": 1, "ccaa": "A", "poblacion_norm": 0.0,
         "consumo_embotellada_norm": 1.0, "agua_no_potable_norm": 1.0, "estres_hidrico": 1.0},
        {"CODAUTO": 2, "ccaa": "B", "poblacion_norm": 0.0,
         "consumo_embotellada_norm": 1.0, "agua_no_potable_norm": 1.0, "estres_hidrico": 0.0},
    ])
    out = puntuacion_ccaa(ccaa).set_index("CODAUTO")
    assert out.at[1, "otros_datos_ccaa"] == pytest.approx(CCAA_WEIGHTS["estres_hidrico"])
    assert out.at[2, "otros_datos_ccaa"] == pytest.approx(0.0)


class TestImputacionSequia:
    """Sections without a gauged station take their region's median, flagged."""

    def _datos(self):
        secciones = pd.DataFrame([
            {"seccion_censal": s, "CODAUTO": 1, "CPRO": 1, "CMUN": m, "municipio": "X",
             "longitud": 0.0, "latitud": 40.0, "poblacion_ideal_norm": 0.5,
             "renta_hogar_2024": 30000, "renta_hogar_norm": 0.5}
            for s, m in [(1, 1), (2, 2), (3, 3)]
        ])
        municipios = pd.DataFrame([
            {"CPRO": 1, "CMUN": m, "generacion_norm": 0.5, "no_potabilidad": 50.0}
            for m in (1, 2, 3)
        ])
        # municipality 3 has no drought reading at all
        sequia = pd.DataFrame([
            {"CPRO": 1, "CMUN": 1, "puntuacion_sequia": 0.0},
            {"CPRO": 1, "CMUN": 2, "puntuacion_sequia": 100.0},
        ])
        ccaa = pd.DataFrame([{"CODAUTO": 1, "ccaa": "R", "poblacion_norm": 1.0,
                              "consumo_embotellada_norm": 1.0, "agua_no_potable_norm": 1.0,
                              "estres_hidrico": 1.0}])
        return {"secciones": secciones, "municipios": municipios,
                "sequia": sequia, "ccaa": ccaa}

    def test_marca_los_imputados(self):
        out = construir_tabla(self._datos()).set_index("seccion_censal")
        assert not out.at[1, "sequia_imputada"]
        assert not out.at[2, "sequia_imputada"]
        assert out.at[3, "sequia_imputada"]

    def test_usa_la_mediana_regional(self):
        out = construir_tabla(self._datos()).set_index("seccion_censal")
        assert out.at[3, "sequia_norm"] == pytest.approx(0.5)

    def test_no_deja_huecos(self):
        out = construir_tabla(self._datos())
        assert out["sequia_norm"].notna().all()

    def test_no_potabilidad_pasa_a_escala_cero_uno(self):
        out = construir_tabla(self._datos())
        assert out["no_potabilidad_norm"].tolist() == [0.5, 0.5, 0.5]
