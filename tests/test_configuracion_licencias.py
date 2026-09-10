"""
POST /licenses/configuracion, tras perder la dimension de anio.

Sin anio, (tipo, categoria) es la unica identidad de una fila de
ConfiguracionLicencias, y no hay restriccion de base que la proteja: se
chequea a mano antes de insertar.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_configuracion
from tests.fakes import FakeSession

EXISTE_QUERY = "SELECT TOP 1 id FROM ConfiguracionLicencias WHERE tipo = :tipo AND categoria = :categoria"


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
