"""
Los tres defectos de /licenses/aplicar.

Los tres tenian el mismo efecto: descontarle dias a quien no corresponde.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import resolver_licencia

LIC_A = {"id": 1, "employeeId": 10, "type": "Vacaciones"}
LIC_B = {"id": 2, "employeeId": 20, "type": "Vacaciones"}


def test_una_sola_candidata_se_aplica():
    assert resolver_licencia([LIC_A], None)["id"] == 1


def test_dos_candidatas_cortan_en_vez_de_elegir():
    """Dos personas tomandose la misma semana es habitual. Antes elegia la
    primera en silencio y le aprobaba la licencia al empleado equivocado."""
    with pytest.raises(HTTPException) as e:
        resolver_licencia([LIC_A, LIC_B], None)
    assert e.value.status_code == 409


def test_el_license_id_pedido_desempata():
    """Con el id explicito no hay ambiguedad posible."""
    assert resolver_licencia([LIC_A, LIC_B], 2)["id"] == 2


def test_un_license_id_que_no_esta_entre_las_candidatas_corta():
    with pytest.raises(HTTPException) as e:
        resolver_licencia([LIC_A, LIC_B], 99)
    assert e.value.status_code == 404


def test_sin_candidatas_corta_en_vez_de_crear():
    """Antes creaba la licencia con el employeeId del payload, que es el del
    mensaje y por lo tanto el del supervisor: le descontaba los dias a el."""
    with pytest.raises(HTTPException) as e:
        resolver_licencia([], None)
    assert e.value.status_code == 404


def test_el_tipo_sale_de_la_licencia_y_no_del_payload():
    """El frontend manda type 'Vacaciones' fijo: una licencia por Nacimiento
    aprobada desde ese panel descontaba dias de vacaciones."""
    lic = resolver_licencia([{"id": 3, "employeeId": 10, "type": "Nacimiento"}], None)
    assert lic["type"] == "Nacimiento"


def test_ambiguedad_llega_como_409_no_como_500():
    """El bug real: resolver_licencia levanta HTTPException, pero el except
    generico del endpoint la atrapaba igual y la convertia en un 500 opaco."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.licenses import router, get_db, require_rrhh_auth

    app = FastAPI()
    app.include_router(router)

    class _FakeDbAmbiguo:
        def execute(self, *a, **k):
            class _R:
                def mappings(self_inner):
                    return self_inner
                def all(self_inner):
                    return [
                        {"id": 1, "employeeId": 10, "type": "Vacaciones"},
                        {"id": 2, "employeeId": 20, "type": "Vacaciones"},
                    ]
            return _R()
        def rollback(self): pass
        def commit(self): pass

    app.dependency_overrides[get_db] = lambda: _FakeDbAmbiguo()
    app.dependency_overrides[require_rrhh_auth] = lambda: {"id": 1, "username": "rrhh_test"}
    client = TestClient(app)

    resp = client.post("/licenses/aplicar", json={
        "employeeId": 99,
        "startDate": "2026-01-01",
        "endDate": "2026-01-05",
        "days": 5,
    })

    assert resp.status_code == 409, f"esperaba 409, llego {resp.status_code}: {resp.text}"
