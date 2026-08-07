import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


EXTERNO = {
    "idUsuario": "1915881e-fcf9-4caa-b5b0-998b6b314653",
    "nombreUsuario": "EmilianoRojo",
    "claveUsuario": hash_bcrypt("secreto"),
    "anulado": False,
    "idPersona": 232,
    "nombrePersona": "Emiliano",
    "apellidoPersona": "Rojo",
    "numeroDocPersona": "35123456",
    "sexoPersona": "M",
    "telefonoPersona": "3794123456",
    "emailPersona": "erojo@institucion.gob.ar",
    "fechaNacPersona": None,
    "fotoPersona": None,
}


# -- fila_usuario -------------------------------------------------------------

def test_fila_marca_vinculado_cuando_el_dni_existe():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {"35123456": 264})

    assert fila["vinculado"] is True
    assert fila["employeeId"] == 264
    assert fila["dni"] == "35123456"
    assert fila["nombreUsuario"] == "EmilianoRojo"
    assert fila["anulado"] is False


def test_fila_marca_no_vinculado_cuando_el_dni_no_existe():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {})

    assert fila["vinculado"] is False
    assert fila["employeeId"] is None


def test_fila_de_persona_sin_dni_no_explota():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario({**EXTERNO, "numeroDocPersona": None}, {"35123456": 264})

    assert fila["dni"] == ""
    assert fila["vinculado"] is False


def test_fila_nunca_expone_la_clave():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {})

    assert "claveUsuario" not in fila
    assert EXTERNO["claveUsuario"] not in str(fila)


# -- importar_usuarios --------------------------------------------------------

def _db_vacia():
    return FakeSession({
        "INSERT INTO Employee": [{"id": 300}],
        "INSERT INTO [User]": [{"id": 9}],
    })


def test_importar_da_de_alta_un_usuario_nuevo():
    from app.routes.obrasocial import importar_usuarios

    db = _db_vacia()
    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})

    resumen = importar_usuarios(db, db_os, [EXTERNO["idUsuario"]])

    assert resumen == {"importados": 1, "ya_existian": 0, "errores": []}
    assert "INSERT INTO Employee" in db.sql_ejecutado()


def test_importar_saltea_a_quien_ya_tiene_usuario():
    from app.routes.obrasocial import importar_usuarios

    db = FakeSession({
        "FROM [User]\n        WHERE usuario": [{"id": 7, "usuario": "EmilianoRojo", "origen": "obrasocial"}],
    })
    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})

    resumen = importar_usuarios(db, db_os, [EXTERNO["idUsuario"]])

    assert resumen["ya_existian"] == 1
    assert resumen["importados"] == 0
    assert "INSERT INTO" not in db.sql_ejecutado()


def test_un_elemento_fallido_no_aborta_el_lote():
    from app.routes.obrasocial import importar_usuarios

    sin_dni = {**EXTERNO, "idUsuario": "otro-id", "nombreUsuario": "SinDni",
               "numeroDocPersona": None}
    db = _db_vacia()
    db_os = FakeSession({"FROM [ObraSocial]": [sin_dni, EXTERNO]})

    resumen = importar_usuarios(db, db_os, ["otro-id", EXTERNO["idUsuario"]])

    assert resumen["importados"] == 1
    assert len(resumen["errores"]) == 1
    assert resumen["errores"][0]["idUsuario"] == "otro-id"
    assert "documento" in resumen["errores"][0]["motivo"]


def test_importar_sin_ids_es_un_400():
    from app.routes.obrasocial import importar_usuarios

    with pytest.raises(HTTPException) as e:
        importar_usuarios(_db_vacia(), FakeSession(), [])
    assert e.value.status_code == 400
