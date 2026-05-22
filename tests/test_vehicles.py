"""Tests para vehicles.py — detección de marca/modelo/trim."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vehicles as v


class TestFindModelBugCases:
    """Los casos que motivaron el fix (#1)."""

    def test_4x4_no_matchea_x4_de_bmw(self):
        # Antes "Toyota 4x4" → modelo 'x4' (de BMW). Ahora None (scope por marca + tokens).
        assert v.find_model_in_text("Toyota 4x4 Diesel", "toyota") is None

    def test_innova_ahora_detectado(self):
        assert v.find_model_in_text("Toyota Innova 2.7 Srv 6at", "toyota") == "innova"

    def test_2008_no_es_208(self):
        assert v.find_model_in_text("Peugeot 2008 Allure 1.6", "peugeot") == "2008"

    def test_208(self):
        assert v.find_model_in_text("Peugeot 208 Feline", "peugeot") == "208"

    def test_gol_no_es_golf(self):
        assert v.find_model_in_text("Volkswagen Gol Trend 1.6", "volkswagen") == "gol"

    def test_golf_gti_mas_especifico(self):
        assert v.find_model_in_text("Volkswagen Golf GTI", "volkswagen") == "golf_gti"

    def test_corolla_cross_mas_especifico(self):
        assert v.find_model_in_text("Toyota Corolla Cross XEI", "toyota") == "corolla_cross"

    def test_numerico_con_sufijo_de_motor(self):
        # "118i" debe matchear el modelo 118 de BMW
        assert v.find_model_in_text("BMW 118i Sport", "bmw") == "118"
        assert v.find_model_in_text("Mercedes C200 Avantgarde", "mercedes") == "c200"


class TestFindModelGeneral:
    def test_sin_marca_usa_fallback_global(self):
        assert v.find_model_in_text("Corolla 1.8 XEI") == "corolla"

    def test_modelo_desconocido_es_none(self):
        assert v.find_model_in_text("Nave Espacial XYZ Turbo", "toyota") is None

    def test_x4_dentro_de_4x4_nunca(self):
        # incluso sin marca, "4x4" no debe dar x4
        assert v.find_model_in_text("Camioneta 4x4 impecable") != "x4"

    def test_208_no_matchea_dentro_de_2080(self):
        assert v.find_model_in_text("Peugeot 2080 raro", "peugeot") != "208"

    def test_texto_vacio(self):
        assert v.find_model_in_text("", "toyota") is None
        assert v.find_model_in_text(None, "toyota") is None


class TestFindBrand:
    def test_mercedes_variantes(self):
        assert v.find_brand_in_text("Mercedes-Benz C200") == "mercedes"

    def test_normaliza(self):
        assert v.normalize_brand("Mercedes-Benz") == "mercedes"
        assert v.normalize_brand("VW") == "volkswagen"

    def test_none(self):
        assert v.find_brand_in_text("texto sin marca conocida") is None


class TestFindTrim:
    def test_detecta_trim_largo(self):
        assert v.find_trim("Volkswagen Golf GTI") == "gti"

    def test_no_falso_positivo_por_substring(self):
        # 'st' no debe matchear dentro de palabras (tokens, no substring)
        assert v.find_trim("Toyota Etios sedan") in (None, "sedan")


class TestMakeModelKey:
    def test_con_trim(self):
        assert v.make_model_key("toyota", "corolla", 2020, "xei") == "toyota_corolla_2020_xei"

    def test_sin_modelo(self):
        assert v.make_model_key("toyota", None, 2020) == "toyota_other_2020"


class TestClasificarUbicacion:
    def test_cordoba_en_zona(self):
        prov, region, en = v.clasificar_ubicacion("Río Cuarto - Córdoba")
        assert prov == "Córdoba" and en is True

    def test_mendoza_cuyo(self):
        prov, region, en = v.clasificar_ubicacion("Godoy Cruz - Mendoza")
        assert region == "Cuyo" and en is True

    def test_tucuman_noa(self):
        _, region, en = v.clasificar_ubicacion("San Miguel de Tucumán - Tucumán")
        assert region == "NOA" and en is True

    def test_santa_fe_en_zona(self):
        prov, _, en = v.clasificar_ubicacion("Rosario - Santa Fe")
        assert prov == "Santa Fe" and en is True

    def test_buenos_aires_en_zona(self):
        _, _, en = v.clasificar_ubicacion("Pergamino - Buenos Aires Interior")
        assert en is True

    def test_bsas_gba_en_zona(self):
        _, _, en = v.clasificar_ubicacion("Lomas de Zamora - Bs.As. G.B.A. Sur")
        assert en is True

    def test_patagonia_fuera(self):
        _, _, en = v.clasificar_ubicacion("Neuquén - Neuquén")
        assert en is False

    def test_vacio(self):
        assert v.clasificar_ubicacion("") == (None, None, False)


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
