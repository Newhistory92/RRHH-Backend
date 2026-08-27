"""
Tests del "leido" de la campanita de notificaciones (GET /licenses/notificaciones
y PATCH /licenses/notificaciones/{id}/leer).

Bug que motiva estos tests: el status de cada notificacion venia hardcodeado
a "nueva" en la respuesta del GET, y no existia forma de marcarla como leida
-- por eso el contador de la campanita nunca bajaba aunque el usuario ya
hubiera abierto el mensaje. La columna Message.leida y el nuevo endpoint
PATCH resuelven eso.
"""
import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession


def test_get_notificaciones_devuelve_nueva_cuando_no_leida():
    from app.routes.licenses import get_notificaciones

    db = FakeSession({
        "FROM Message": [
            {"id": 1, "text": "Tu licencia fue aprobada", "createdAt": "2026-01-10", "leida": False},
        ],
    })

    resultado = get_notificaciones(employee_id=42, db=db)

    assert resultado["notifications"][0]["status"] == "nueva"


def test_get_notificaciones_devuelve_leida_cuando_ya_fue_marcada():
    from app.routes.licenses import get_notificaciones

    db = FakeSession({
        "FROM Message": [
            {"id": 1, "text": "Tu licencia fue aprobada", "createdAt": "2026-01-10", "leida": True},
        ],
    })

    resultado = get_notificaciones(employee_id=42, db=db)

    assert resultado["notifications"][0]["status"] == "leida"


def test_marcar_notificacion_leida_actualiza_y_devuelve_success():
    from app.routes.licenses import marcar_notificacion_leida

    db = FakeSession({
        "UPDATE Message SET leida = 1": [{"id": 1}],  # simula 1 fila afectada
    })

    resultado = marcar_notificacion_leida(notif_id=1, db=db)

    assert resultado == {"success": True}
    assert db.commits == 1
    # El UPDATE se armo con el id correcto como parametro nombrado
    sql, params = db.ejecutadas[-1]
    assert "UPDATE Message SET leida = 1" in sql
    assert params == {"id": 1}


def test_marcar_notificacion_leida_404_si_no_existe():
    from app.routes.licenses import marcar_notificacion_leida

    db = FakeSession({})  # ningun fragmento matchea -> rowcount 0

    with pytest.raises(HTTPException) as exc:
        marcar_notificacion_leida(notif_id=999, db=db)

    assert exc.value.status_code == 404
