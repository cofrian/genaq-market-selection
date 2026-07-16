import pandas as pd
import pytest

from src.calidad_agua import (LIMITES_PARAMETROS, calcular_no_potabilidad,
                             evaluar_muestra, evaluar_muestras)


class TestEvaluarMuestra:
    def test_valor_dentro_del_limite_pasa(self):
        assert evaluar_muestra({"Plomo": 5}) == {"Plomo": True}

    def test_valor_sobre_el_limite_falla(self):
        assert evaluar_muestra({"Plomo": 15}) == {"Plomo": False}

    def test_limite_es_inclusivo(self):
        assert evaluar_muestra({"Plomo": LIMITES_PARAMETROS["Plomo"]}) == {"Plomo": True}

    def test_rango_acepta_los_extremos(self):
        assert evaluar_muestra({"PH": 6.5})["PH"]
        assert evaluar_muestra({"PH": 9.5})["PH"]

    def test_rango_rechaza_fuera(self):
        assert not evaluar_muestra({"PH": 6.4})["PH"]
        assert not evaluar_muestra({"PH": 9.6})["PH"]

    def test_microbiologico_cualquier_presencia_falla(self):
        assert evaluar_muestra({"Escherichia coli": 0})["Escherichia coli"]
        assert not evaluar_muestra({"Escherichia coli": 1})["Escherichia coli"]

    def test_parametro_desconocido_se_ignora(self):
        """Unlisted parameters carry no legal limit, so they get no verdict."""
        assert evaluar_muestra({"Parametro Inventado": 999}) == {}

    def test_valor_no_numerico_se_ignora(self):
        assert evaluar_muestra({"Plomo": "sin dato"}) == {}

    def test_acepta_diccionario_serializado(self):
        assert evaluar_muestra("{'Plomo': 5}") == {"Plomo": True}


class TestEvaluarMuestras:
    def _df(self, analisis):
        return pd.DataFrame([{"Analisis_Valor": analisis}])

    def test_cuenta_aciertos_y_fallos(self):
        out = evaluar_muestras(self._df({"Plomo": 5, "Nitrato": 80, "PH": 7.0}))
        assert out["valores_true"].iloc[0] == 2
        assert out["valores_false"].iloc[0] == 1

    def test_potable_solo_si_todo_pasa(self):
        assert evaluar_muestras(self._df({"Plomo": 5, "PH": 7.0}))["potable"].iloc[0]
        assert not evaluar_muestras(self._df({"Plomo": 50, "PH": 7.0}))["potable"].iloc[0]

    def test_muestra_sin_parametros_evaluables_no_es_potable(self):
        """No gradeable reading means unknown, which must not pass as potable."""
        assert not evaluar_muestras(self._df({"Parametro Inventado": 1}))["potable"].iloc[0]

    def test_extrae_ph_y_dureza(self):
        out = evaluar_muestras(self._df({"PH": 8.1, "Dureza Total (CaCO3)": 320}))
        assert out["pH"].iloc[0] == 8.1
        assert out["dureza"].iloc[0] == 320

    def test_acepta_analisis_serializado(self):
        """An intermediate CSV round-trips the dict as text; it must still work."""
        out = evaluar_muestras(self._df("{'PH': 8.1, 'Plomo': 5}"))
        assert out["pH"].iloc[0] == 8.1
        assert out["valores_true"].iloc[0] == 2

    def test_analisis_vacio_no_rompe(self):
        out = evaluar_muestras(self._df({}))
        assert out["valores_true"].iloc[0] == 0
        assert not out["potable"].iloc[0]


class TestNoPotabilidad:
    def _fila(self, **kw):
        base = {"dureza_media": 300.0, "ph_medio": 7.0,
                "parametros_ok": 10, "parametros_fuera_rango": 0}
        return pd.DataFrame([{**base, **kw}])

    def test_agua_perfecta_puntua_cero(self):
        assert calcular_no_potabilidad(self._fila()).iloc[0] == pytest.approx(0.0)

    def test_siempre_entre_cero_y_cien(self):
        extremo = self._fila(dureza_media=5000.0, ph_medio=14.0,
                             parametros_ok=0, parametros_fuera_rango=500)
        score = calcular_no_potabilidad(extremo).iloc[0]
        assert 0.0 <= score <= 100.0

    def test_dureza_alta_penaliza(self):
        blanda = calcular_no_potabilidad(self._fila(dureza_media=300.0)).iloc[0]
        dura = calcular_no_potabilidad(self._fila(dureza_media=900.0)).iloc[0]
        assert dura > blanda

    def test_dureza_muy_baja_tambien_penaliza(self):
        """Below 150 mg/L the water is aggressive, not 'better'."""
        ideal = calcular_no_potabilidad(self._fila(dureza_media=300.0)).iloc[0]
        blandisima = calcular_no_potabilidad(self._fila(dureza_media=20.0)).iloc[0]
        assert blandisima > ideal

    def test_dureza_ausente_no_penaliza(self):
        assert calcular_no_potabilidad(self._fila(dureza_media=None)).iloc[0] == pytest.approx(0.0)

    def test_mas_fallos_penaliza_mas(self):
        pocos = calcular_no_potabilidad(self._fila(parametros_ok=9, parametros_fuera_rango=1)).iloc[0]
        muchos = calcular_no_potabilidad(self._fila(parametros_ok=1, parametros_fuera_rango=9)).iloc[0]
        assert muchos > pocos

    def test_sin_muestras_no_penaliza_por_fallos(self):
        out = calcular_no_potabilidad(self._fila(parametros_ok=0, parametros_fuera_rango=0))
        assert out.iloc[0] == pytest.approx(0.0)
