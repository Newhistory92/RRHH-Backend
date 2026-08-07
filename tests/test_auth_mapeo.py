from datetime import datetime

import pytest

from app.services.auth_providers import mapeo


PERSONA_COMPLETA = {
    "nombrePersona": "Emiliano",
    "apellidoPersona": "Rojo",
    "numeroDocPersona": "35123456",
    "sexoPersona": "M",
    "telefonoPersona": "3794123456",
    "emailPersona": "erojo@institucion.gob.ar",
    "fechaNacPersona": datetime(1992, 5, 14),
    "fotoPersona": "data:image/png;base64,AAA",
}


# -- nombre_completo ----------------------------------------------------------

def test_nombre_completo_une_nombre_y_apellido():
    assert mapeo.nombre_completo(PERSONA_COMPLETA) == "Emiliano Rojo"


def test_nombre_completo_sin_apellido_no_deja_espacio_colgando():
    assert mapeo.nombre_completo({"nombrePersona": "Emiliano"}) == "Emiliano"


def test_nombre_completo_recorta_espacios_de_la_base():
    persona = {"nombrePersona": "  Emiliano  ", "apellidoPersona": " Rojo "}
    assert mapeo.nombre_completo(persona) == "Emiliano Rojo"


def test_nombre_completo_de_persona_vacia_es_cadena_vacia():
    assert mapeo.nombre_completo({}) == ""


# -- email --------------------------------------------------------------------

def test_email_preferido_usa_el_de_la_persona():
    assert mapeo.email_preferido(PERSONA_COMPLETA, "EmilianoRojo") == "erojo@institucion.gob.ar"


def test_email_preferido_cae_al_placeholder_si_esta_vacio():
    persona = {**PERSONA_COMPLETA, "emailPersona": "   "}
    assert mapeo.email_preferido(persona, "EmilianoRojo") == "EmilianoRojo@sin-email.local"


def test_email_preferido_cae_al_placeholder_si_es_nulo():
    persona = {**PERSONA_COMPLETA, "emailPersona": None}
    assert mapeo.email_preferido(persona, "EmilianoRojo") == "EmilianoRojo@sin-email.local"


def test_placeholder_usa_el_dominio_reservado():
    assert mapeo.placeholder_email("Juan") == f"Juan@{mapeo.DOMINIO_SIN_EMAIL}"


# -- persona_a_employee -------------------------------------------------------

def test_persona_a_employee_mapea_todos_los_campos():
    assert mapeo.persona_a_employee(PERSONA_COMPLETA, "EmilianoRojo") == {
        "dni": "35123456",
        "name": "Emiliano Rojo",
        "email": "erojo@institucion.gob.ar",
        "gender": "M",
        "phone": "3794123456",
        "birthDate": datetime(1992, 5, 14),
        "photo": "data:image/png;base64,AAA",
    }


def test_persona_a_employee_normaliza_el_dni_numerico():
    # La base institucional puede devolver el documento como int.
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": 35123456}
    assert mapeo.persona_a_employee(persona, "EmilianoRojo")["dni"] == "35123456"


def test_persona_a_employee_recorta_espacios_del_dni():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": " 35123456 "}
    assert mapeo.persona_a_employee(persona, "EmilianoRojo")["dni"] == "35123456"


def test_persona_sin_dni_no_se_puede_mapear():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": None}
    with pytest.raises(ValueError, match="documento"):
        mapeo.persona_a_employee(persona, "EmilianoRojo")


def test_persona_con_dni_vacio_no_se_puede_mapear():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": "   "}
    with pytest.raises(ValueError, match="documento"):
        mapeo.persona_a_employee(persona, "EmilianoRojo")
