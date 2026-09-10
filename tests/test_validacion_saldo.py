"""
El backend rechaza pedir mas dias de los que hay.

Hasta ahora el unico limite era el selector de fechas del navegador: un POST
directo entraba sin objecion.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession


def _payload(dias: int, tipo: str = "Particular") -> dict:
    return {
        "type": tipo,
        "startDate": "2026-11-10T00:00:00",
        "endDate": "2026-11-20T00:00:00",
        "duration": dias,
        "employeeId": 8,
        "supervisorId": 3,
        "mensajeOriginal": "test",
    }


def _db():
    return FakeSession({
        "SELECT e.gender": [{
            "gender": "Masculino", "employee_name": "Test",
            "tipoContrato": "permanente", "fechaIngreso": None,
            "roleName": "user",
        }],
        # Permite que la insercion de la licencia (y su OUTPUT INSERTED.id)
        # se resuelva sin TypeError, para que un test pueda seguir el
        # camino de exito hasta el final en lugar de cortar a mitad de
        # camino con un 500 disfrazado de HTTPException.
        "INSERT INTO License": [(101,)],
    })


DISPONIBLES_5 = {"tipos": [{"nombre": "Particular", "diasTotales": 5,
                            "consumidos": 0, "disponibles": 5}]}


def test_rechaza_pedir_mas_de_lo_disponible():
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        with pytest.raises(HTTPException) as e:
            create_license_request(
                data=_payload(6), db=_db(),
                current_user={"employeeId": 8, "permisos": set()},
            )
    assert e.value.status_code == 400
    assert "5" in str(e.value.detail)


def test_permite_pedir_exactamente_el_limite():
    """El borde tiene que entrar: pedir justo lo que hay no es excederse.

    Antes este test tragaba cualquier HTTPException y solo miraba que el
    mensaje no dijera "saldo" -- contra FakeSession sin fila para el INSERT,
    la insercion de la licencia fallaba con TypeError (None[0]), que el
    propio create_license_request reconvertia en un HTTPException 500, y
    el test lo dejaba pasar sin darse cuenta de que nunca habia probado el
    camino de exito. Ahora _db() responde el INSERT y el test afirma
    exactamente el resultado esperado, sin capturar nada."""
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        resultado = create_license_request(
            data=_payload(5), db=_db(),
            current_user={"employeeId": 8, "permisos": set()},
        )
    assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}


def test_la_validacion_tambien_alcanza_a_rrhh():
    """Se decidio criterio parejo: RRHH tampoco puede exceder el saldo.

    El permiso que habilita a pedir a nombre de otro es licencias.configurar
    (no rrhh.gestionar): con cualquier otro, el endpoint corta antes con un
    403 y este test no llegaria a probar lo que dice probar."""
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        with pytest.raises(HTTPException) as e:
            create_license_request(
                data=_payload(6), db=_db(),
                current_user={"employeeId": 99, "permisos": {"licencias.configurar"}},
            )
    assert e.value.status_code == 400
    assert "5" in str(e.value.detail)
