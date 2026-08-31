"""
buscar_empleado no traia birthDate, phone ni biometricoId, asi que el
chatbot no podia responder "cual es el cumpleanos de Fulano" o "cual es su
ID de reloj" pese a que esos datos ya estan en Employee -uno via Prisma
(birthDate, phone), el otro agregado por este backend (biometricoId, ver
app/database/marcaciones.py ensure_columna_biometrico).
"""

from tests.fakes import FakeSession

from app.routes import chat as c

FRAG_EMPLEADO = "FROM Employee e"


def test_la_consulta_trae_fecha_nacimiento_telefono_e_id_de_reloj():
    db = FakeSession({FRAG_EMPLEADO: []})
    c._buscar_empleado(db, "Rojo")
    sql = db.sql_ejecutado()
    assert "e.birthDate" in sql
    assert "e.phone" in sql
    assert "e.biometricoId" in sql


def test_devuelve_esos_campos_en_el_resultado():
    db = FakeSession({
        FRAG_EMPLEADO: [{
            "id": 13, "name": "Emiliano Rojo", "dni": "12345678",
            "email": "e@x.com", "phone": "11-2222-3333",
            "birthDate": "1992-03-15", "gender": "M", "status": "Activo",
            "biometricoId": "7", "departamento": "Sistemas", "oficina": "Central",
            "tipoContrato": "Planta", "categoria": "A", "cargo": "Analista",
        }],
    })
    r = c._buscar_empleado(db, "Rojo")
    assert r[0]["birthDate"] == "1992-03-15"
    assert r[0]["phone"] == "11-2222-3333"
    assert r[0]["biometricoId"] == "7"
