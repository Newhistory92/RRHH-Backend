"""
buscar_empleado no traia birthDate, phone ni biometricoId, asi que el
chatbot no podia responder "cual es el cumpleanos de Fulano" o "cual es su
ID de reloj" pese a que esos datos ya estan en Employee -uno via Prisma
(birthDate, phone), el otro agregado por este backend (biometricoId, ver
app/database/marcaciones.py ensure_columna_biometrico).

Despues se amplio a la ficha completa: condicion laboral, horario, jefe
directo y el historial de licencias -este ultimo no sale de un JOIN directo
porque un empleado puede tener varias, asi que se pide aparte y se mezcla en
Python (mismo patron que jornadas_de() con las incidencias).
"""

from tests.fakes import FakeSession

from app.routes import chat as c

FRAG_EMPLEADO = "FROM Employee e"
FRAG_LICENCIAS = "FROM License"


def test_la_consulta_trae_fecha_nacimiento_telefono_e_id_de_reloj():
    db = FakeSession({FRAG_EMPLEADO: []})
    c._buscar_empleado(db, "Rojo")
    sql = db.sql_ejecutado()
    assert "e.birthDate" in sql
    assert "e.phone" in sql
    assert "e.biometricoId" in sql


def test_la_consulta_trae_condicion_laboral_horario_y_jefe():
    db = FakeSession({FRAG_EMPLEADO: []})
    c._buscar_empleado(db, "Rojo")
    sql = db.sql_ejecutado()
    assert "c.fechaIngreso" in sql
    assert "h.horaInicio" in sql
    assert "jefe.name AS jefe" in sql


def test_no_pide_photo_para_no_inflar_la_respuesta():
    db = FakeSession({FRAG_EMPLEADO: []})
    c._buscar_empleado(db, "Rojo")
    assert "e.photo" not in db.sql_ejecutado()


def test_sin_coincidencias_no_consulta_licencias():
    db = FakeSession({FRAG_EMPLEADO: []})
    r = c._buscar_empleado(db, "NoExiste")
    assert r == []
    assert FRAG_LICENCIAS not in db.sql_ejecutado()


def test_devuelve_los_campos_personales_en_el_resultado():
    db = FakeSession({
        FRAG_EMPLEADO: [{
            "id": 13, "name": "Emiliano Rojo", "dni": "12345678",
            "email": "e@x.com", "phone": "11-2222-3333", "address": "Calle Falsa 123",
            "birthDate": "1992-03-15", "gender": "M", "status": "Activo",
            "productivityScore": 8.5, "horas": 2.0, "biometricoId": "7",
            "departamento": "Sistemas", "oficina": "Central", "jefe": "Ana Gerente",
            "tipoContrato": "Planta", "categoria": "A", "cargo": "Analista",
            "fechaIngreso": "2020-01-10", "fechaPlanta": None, "fechaCategoria": None,
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
        }],
    })
    r = c._buscar_empleado(db, "Rojo")
    assert r[0]["birthDate"] == "1992-03-15"
    assert r[0]["phone"] == "11-2222-3333"
    assert r[0]["biometricoId"] == "7"
    assert r[0]["jefe"] == "Ana Gerente"
    assert r[0]["horaInicio"] == 8.0


def test_trae_el_historial_completo_de_licencias_del_empleado():
    db = FakeSession({
        FRAG_EMPLEADO: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_LICENCIAS: [
            {"employeeId": 13, "type": "Vacaciones", "startDate": "2026-01-05",
             "endDate": "2026-01-20", "status": "aprobada"},
            {"employeeId": 13, "type": "Enfermedad", "startDate": "2025-11-02",
             "endDate": "2025-11-04", "status": "aprobada"},
        ],
    })
    r = c._buscar_empleado(db, "Rojo")
    assert len(r[0]["licencias"]) == 2
    assert r[0]["licencias"][0]["tipo"] == "Vacaciones"


def test_empleado_sin_licencias_devuelve_lista_vacia_no_error():
    db = FakeSession({
        FRAG_EMPLEADO: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_LICENCIAS: [],
    })
    r = c._buscar_empleado(db, "Rojo")
    assert r[0]["licencias"] == []


def test_dos_empleados_no_mezclan_licencias_entre_si():
    db = FakeSession({
        FRAG_EMPLEADO: [
            {"id": 13, "name": "Emiliano Rojo"},
            {"id": 21, "name": "Emiliano Rojas"},
        ],
        FRAG_LICENCIAS: [
            {"employeeId": 13, "type": "Vacaciones", "startDate": "2026-01-05",
             "endDate": "2026-01-20", "status": "aprobada"},
        ],
    })
    r = c._buscar_empleado(db, "Emiliano")
    por_id = {e["id"]: e for e in r}
    assert len(por_id[13]["licencias"]) == 1
    assert por_id[21]["licencias"] == []
