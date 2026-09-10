"""
POST/PUT /licenses/configuracion, tras perder la dimension de anio.

Sin anio, (tipo, categoria) es la unica identidad de una fila de
ConfiguracionLicencias, y no hay restriccion de base que la proteja: se
chequea a mano antes de insertar o actualizar.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_configuracion, update_configuracion
from tests.fakes import FakeSession

EXISTE_QUERY = "SELECT TOP 1 id FROM ConfiguracionLicencias WHERE tipo = :tipo AND categoria = :categoria"
EXISTE_QUERY_UPDATE = "AND id <> :id"


def test_rechaza_un_tipo_y_categoria_ya_configurados():
    """Sin esto, una segunda fila para el mismo par duplicaria el SUM de
    diasTotales en todo lugar que lea la configuracion."""
    db = FakeSession({EXISTE_QUERY: [{"id": 1}]})
    with pytest.raises(HTTPException) as e:
        create_configuracion(
            data={"tipo": "permanente", "categoria": "Particular", "diasTotales": 5},
            db=db,
        )
    assert e.value.status_code == 400


def test_permite_un_tipo_y_categoria_nuevos():
    db = FakeSession({
        EXISTE_QUERY: [],
        "INSERT INTO ConfiguracionLicencias": [(99,)],
    })
    resultado = create_configuracion(
        data={"tipo": "permanente", "categoria": "Particular", "diasTotales": 5},
        db=db,
    )
    assert resultado["id"] == 99


def test_editar_rechaza_colisionar_con_otra_fila():
    """Sin esto, se podia editar una fila para que su (tipo, categoria)
    chocara con otra ya existente -- la misma puerta trasera que el chequeo
    del POST cierra, abierta del lado del PUT."""
    db = FakeSession({EXISTE_QUERY_UPDATE: [{"id": 2}]})
    with pytest.raises(HTTPException) as e:
        update_configuracion(
            config_id=1,
            data={"tipo": "permanente", "categoria": "Vacaciones", "diasTotales": 5},
            db=db,
        )
    assert e.value.status_code == 400


def test_editar_permite_guardar_su_propia_fila_sin_cambiar_el_par():
    """El AND id <> :id es clave: editar solo el diasTotales de una fila
    tiene que verla a si misma como 'no hay colision', no como duplicado."""
    db = FakeSession({EXISTE_QUERY_UPDATE: []})
    resultado = update_configuracion(
        config_id=1,
        data={"tipo": "permanente", "categoria": "Vacaciones", "diasTotales": 8},
        db=db,
    )
    assert resultado["message"] == "Configuración actualizada"
