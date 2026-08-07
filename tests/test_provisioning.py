from tests.fakes import FakeSession


DATOS_EMPLEADO = {
    "dni": "35123456",
    "name": "Emiliano Rojo",
    "email": "erojo@institucion.gob.ar",
    "gender": "M",
    "phone": "3794123456",
    "birthDate": None,
    "photo": None,
}


# -- Migracion ----------------------------------------------------------------

def test_ensure_columna_origen_es_idempotente():
    from app.database import provisioning as prov

    db = FakeSession()
    prov.ensure_columna_origen(db)

    sql = db.sql_ejecutado()
    assert "COL_LENGTH('[User]','origen')" in sql
    assert "NVARCHAR(20) NOT NULL DEFAULT 'local'" in sql
    assert db.commits == 1


# -- Lecturas -----------------------------------------------------------------

def test_buscar_user_encuentra_por_usuario_o_email():
    from app.database import provisioning as prov

    fila = {"id": 7, "usuario": "erojo", "origen": "local"}
    db = FakeSession({"FROM [User]": [fila]})

    assert prov.buscar_user(db, "erojo")["id"] == 7
    _, params = db.ejecutadas[0]
    assert params == {"u": "erojo"}


def test_buscar_user_inexistente_devuelve_none():
    from app.database import provisioning as prov

    assert prov.buscar_user(FakeSession(), "fantasma") is None


def test_buscar_employee_por_dni_devuelve_la_fila():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [{"id": 264, "dni": "35123456", "name": "Emiliano Rojo"}]})
    assert prov.buscar_employee_por_dni(db, "35123456")["id"] == 264


def test_employees_por_dni_arma_el_in_con_binds():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [
        {"id": 264, "dni": "35123456"},
        {"id": 265, "dni": " 40999888 "},
    ]})

    mapa = prov.employees_por_dni(db, ["35123456", "40999888", "11111111"])

    assert mapa == {"35123456": 264, "40999888": 265}
    sql, params = db.ejecutadas[0]
    assert ":d0, :d1, :d2" in sql
    assert params == {"d0": "35123456", "d1": "40999888", "d2": "11111111"}
    # Ningun valor interpolado en el SQL: solo binds.
    assert "35123456" not in sql


def test_employees_por_dni_con_lista_vacia_no_consulta():
    from app.database import provisioning as prov

    db = FakeSession()
    assert prov.employees_por_dni(db, []) == {}
    assert db.ejecutadas == []


def test_email_ocupado_es_true_si_hay_fila():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [{"id": 1}]})
    assert prov.email_ocupado(db, "erojo@institucion.gob.ar") is True


def test_email_libre_es_false():
    from app.database import provisioning as prov

    assert prov.email_ocupado(FakeSession(), "nuevo@institucion.gob.ar") is False


def test_user_de_employee_devuelve_el_vinculado():
    from app.database import provisioning as prov

    db = FakeSession({"FROM [User]": [{"id": 7, "usuario": "erojo"}]})
    assert prov.user_de_employee(db, 264)["usuario"] == "erojo"


# -- Escrituras ---------------------------------------------------------------

def test_crear_employee_devuelve_el_id_y_commitea():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO Employee": [{"id": 300}]})
    assert prov.crear_employee(db, DATOS_EMPLEADO) == 300
    assert db.commits == 1


def test_crear_employee_pasa_todos_los_campos_del_mapeo():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO Employee": [{"id": 300}]})
    prov.crear_employee(db, DATOS_EMPLEADO)

    _, params = db.ejecutadas[0]
    for clave, valor in DATOS_EMPLEADO.items():
        assert params[clave] == valor
    assert "updatedAt" in params


def test_crear_user_usa_rol_user_por_defecto():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO [User]": [{"id": 9}]})
    nuevo = prov.crear_user(
        db, usuario="erojo", email="erojo@institucion.gob.ar",
        password_hash="$2b$10$hash", employee_id=300,
        origen=prov.ORIGEN_OBRASOCIAL,
    )

    assert nuevo == 9
    _, params = db.ejecutadas[0]
    assert params["roleId"] == prov.ROLE_USER == 2
    assert params["origen"] == "obrasocial"
    assert params["employeeId"] == 300
    assert db.commits == 1


def test_actualizar_password_escribe_el_hash_nuevo():
    from app.database import provisioning as prov

    db = FakeSession()
    prov.actualizar_password(db, 7, "$2b$10$nuevo")

    sql, params = db.ejecutadas[0]
    assert "UPDATE [User]" in sql
    assert params == {"p": "$2b$10$nuevo", "id": 7}
    assert db.commits == 1
