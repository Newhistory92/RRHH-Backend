"""
Regresion: _ausencias_recientes usaba a.motivo, columna que no existe.

La tabla Ausencia la crea prisma/schema.prisma (frontend), no este backend;
su columna es "reason". Antes de este fix, la herramienta ausencias_recientes
del chatbot fallaba en cada llamada con "Invalid column name 'motivo'",
que el chat reportaba como "hubo un error" generico.
"""

from tests.fakes import FakeSession

from app.routes import chat as c


def test_la_consulta_usa_reason_y_no_motivo():
    db = FakeSession({"FROM Ausencia a": []})
    c._ausencias_recientes(db)
    sql = db.sql_ejecutado()
    assert "a.reason AS motivo" in sql
    assert "a.motivo" not in sql


def test_devuelve_las_filas_con_clave_motivo_en_castellano():
    db = FakeSession({
        "FROM Ausencia a": [
            {"name": "Emiliano Rojo", "fecha": "2026-08-20", "motivo": "Turno medico"},
        ]
    })
    r = c._ausencias_recientes(db)
    assert r[0]["motivo"] == "Turno medico"
