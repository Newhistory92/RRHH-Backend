import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


HASH_SECRETO = hash_bcrypt("secreto")
HASH_NUEVO = hash_bcrypt("cambiada")

EXTERNO = {
    "idUsuario": "1915881e-fcf9-4caa-b5b0-998b6b314653",
    "nombreUsuario": "EmilianoRojo",
    "claveUsuario": HASH_SECRETO,
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

USER_PROVISIONADO = {
    "id": 7,
    "usuario": "EmilianoRojo",
    "email": "erojo@institucion.gob.ar",
    "password": HASH_SECRETO,
    "roleId": 2,
    "employeeId": 264,
    "activo": True,
    "origen": "obrasocial",
}

USER_LOCAL = {**USER_PROVISIONADO, "id": 1, "usuario": "admin", "roleId": 1, "origen": "local"}


def _proveedor(externo=EXTERNO):
    """Proveedor con una sesion ObraSocial falsa que devuelve `externo`."""
    from app.services.auth_providers.obrasocial import ObraSocialAuthProvider

    filas = [externo] if externo else []
    sesion_os = FakeSession({"FROM [ObraSocial]": filas})
    return ObraSocialAuthProvider(session_factory=lambda: sesion_os), sesion_os


def _db(user_row=None, employee_row=None, user_vinculado=None,
        email_ocupado=False, nuevo_employee_id=300, nuevo_user_id=9):
    """Sesion RRHH falsa. Las claves son fragmentos distintivos de cada query."""
    return FakeSession({
        "FROM [User]\n        WHERE usuario": [user_row] if user_row else [],
        "SELECT id, dni, name FROM Employee": [employee_row] if employee_row else [],
        "SELECT id, usuario FROM [User]": [user_vinculado] if user_vinculado else [],
        "SELECT id FROM Employee WHERE email": [{"id": 1}] if email_ocupado else [],
        "INSERT INTO Employee": [{"id": nuevo_employee_id}],
        "INSERT INTO [User]": [{"id": nuevo_user_id}],
    })


# -- Camino 1: usuario local puro ---------------------------------------------

def test_usuario_local_no_consulta_obrasocial():
    proveedor, sesion_os = _proveedor()

    resultado = proveedor.autenticar(_db(user_row=USER_LOCAL), "admin", "secreto")

    assert resultado.roleId == 1
    assert sesion_os.ejecutadas == []


def test_usuario_local_inhabilitado_da_403():
    proveedor, _ = _proveedor()
    inactivo = {**USER_LOCAL, "activo": False}

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=inactivo), "admin", "secreto")
    assert e.value.status_code == 403


# -- Camino 2: usuario ya provisionado ----------------------------------------

def test_usuario_provisionado_entra_con_su_hash_local():
    proveedor, _ = _proveedor()

    resultado = proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "secreto")

    assert resultado.usuario == "EmilianoRojo"
    assert resultado.employeeId == 264


def test_usuario_anulado_en_obrasocial_da_403():
    proveedor, _ = _proveedor({**EXTERNO, "anulado": True})

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "secreto")

    assert e.value.status_code == 403
    assert "institución" in e.value.detail


def test_clave_cambiada_en_obrasocial_se_sincroniza_y_deja_entrar():
    proveedor, _ = _proveedor({**EXTERNO, "claveUsuario": HASH_NUEVO})
    db = _db(user_row=USER_PROVISIONADO)

    resultado = proveedor.autenticar(db, "EmilianoRojo", "cambiada")

    assert resultado.employeeId == 264
    assert "UPDATE [User] SET password" in db.sql_ejecutado()


def test_clave_sin_cambios_no_escribe_en_la_base():
    proveedor, _ = _proveedor()
    db = _db(user_row=USER_PROVISIONADO)

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert "UPDATE [User] SET password" not in db.sql_ejecutado()


def test_password_incorrecta_de_usuario_provisionado_da_401():
    proveedor, _ = _proveedor()

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "otra")
    assert e.value.status_code == 401


# -- Camino 3: primer login ---------------------------------------------------

def test_primer_login_crea_employee_y_user():
    proveedor, _ = _proveedor()
    db = _db()

    resultado = proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert resultado.usuario == "EmilianoRojo"
    assert resultado.roleId == 2
    assert resultado.employeeId == 300
    sql = db.sql_ejecutado()
    assert "INSERT INTO Employee" in sql
    assert "INSERT INTO [User]" in sql


def test_primer_login_copia_el_hash_de_obrasocial():
    proveedor, _ = _proveedor()
    db = _db()

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    inserts = [p for sql, p in db.ejecutadas if "INSERT INTO [User]" in sql]
    assert inserts[0]["password"] == HASH_SECRETO
    assert inserts[0]["origen"] == "obrasocial"


def test_primer_login_reutiliza_el_employee_existente_por_dni():
    proveedor, _ = _proveedor()
    db = _db(employee_row={"id": 264, "dni": "35123456", "name": "Emiliano Rojo"})

    resultado = proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert resultado.employeeId == 264
    assert "INSERT INTO Employee" not in db.sql_ejecutado()


def test_usuario_inexistente_en_ambos_lados_da_401():
    proveedor, _ = _proveedor(externo=None)

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(), "fantasma", "secreto")
    assert e.value.status_code == 401


def test_password_incorrecta_no_provisiona_nada():
    proveedor, _ = _proveedor()
    db = _db()

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(db, "EmilianoRojo", "otra")

    assert e.value.status_code == 401
    assert "INSERT INTO" not in db.sql_ejecutado()


def test_anulado_no_provisiona_nada():
    proveedor, _ = _proveedor({**EXTERNO, "anulado": True})
    db = _db()

    with pytest.raises(HTTPException):
        proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert "INSERT INTO" not in db.sql_ejecutado()


# -- Casos borde del provisioning ---------------------------------------------

def test_persona_sin_dni_da_400():
    proveedor, _ = _proveedor({**EXTERNO, "numeroDocPersona": None})

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(), "EmilianoRojo", "secreto")

    assert e.value.status_code == 400
    assert "documento" in e.value.detail


def test_dni_ya_vinculado_a_otro_usuario_da_409():
    proveedor, _ = _proveedor()
    db = _db(
        employee_row={"id": 264, "dni": "35123456", "name": "Emiliano Rojo"},
        user_vinculado={"id": 3, "usuario": "otro.usuario"},
    )

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert e.value.status_code == 409
    assert "otro.usuario" in e.value.detail


def test_email_duplicado_cae_al_placeholder():
    proveedor, _ = _proveedor()
    db = _db(email_ocupado=True)

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    inserts = [p for sql, p in db.ejecutadas if "INSERT INTO Employee" in sql]
    assert inserts[0]["email"] == "EmilianoRojo@sin-email.local"


# -- Registro del proveedor ---------------------------------------------------

def test_get_provider_devuelve_el_proveedor_institucional(monkeypatch):
    from app.services import auth_providers
    from app.services.auth_providers.obrasocial import ObraSocialAuthProvider

    monkeypatch.setenv("AUTH_PROVIDER", "obrasocial")
    assert isinstance(auth_providers.get_provider(), ObraSocialAuthProvider)


# -- Consultas a la base institucional ----------------------------------------

def test_buscar_por_ids_arma_el_in_con_binds():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})
    os_db.buscar_por_ids(db_os, ["aaa", "bbb"])

    sql, params = db_os.ejecutadas[0]
    assert ":id0, :id1" in sql
    assert params == {"id0": "aaa", "id1": "bbb"}
    assert "aaa" not in sql


def test_buscar_por_ids_con_lista_vacia_no_consulta():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession()
    assert os_db.buscar_por_ids(db_os, []) == []
    assert db_os.ejecutadas == []


def test_las_consultas_institucionales_son_de_solo_lectura():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})
    os_db.listar(db_os)
    os_db.buscar_por_nombre(db_os, "EmilianoRojo")
    os_db.buscar_por_ids(db_os, ["aaa"])

    sql = db_os.sql_ejecutado().upper()
    for prohibido in ("INSERT", "UPDATE", "DELETE", "MERGE", "DROP"):
        assert prohibido not in sql
