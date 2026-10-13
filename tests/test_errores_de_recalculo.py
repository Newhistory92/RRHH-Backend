"""
Los errores del ultimo barrido completo, para que dejen de ser invisibles.

El recalculo masivo esta hecho a proposito para que un empleado que falla no
aborte el resto: se registra en RecalculoLog.errores y se sigue. Correcto
-un legajo roto no puede dejar sin asistencia a toda la planta- pero sin nadie
que lea ese registro, el empleado queda sin calcular indefinidamente y en
silencio. Paso de verdad: cuatro corridas nocturnas seguidas guardaron el mismo
TypeError y se descubrio recien cuando el usuario miro la pantalla.
"""

from datetime import datetime

from app.database.asistencia_auditoria import errores_del_ultimo_barrido
from tests.fakes import FakeSession

LIMPIA = {"id": 110, "origen": "nocturno", "procesados": 5,
          "errores": None, "finalizadoAt": datetime(2026, 10, 14, 3, 0)}
CON_ERROR = {
    "id": 109, "origen": "manual", "procesados": 4,
    "errores": '[{"employeeId": 8, "error": "TypeError: no se puede comparar"}]',
    "finalizadoAt": datetime(2026, 10, 13, 7, 51),
}


def test_sin_errores_no_hay_nada_que_mostrar():
    """La ultima masiva salio limpia: el panel no tiene que aparecer."""
    db = FakeSession({"origen IN": [LIMPIA]})
    assert errores_del_ultimo_barrido(db) is None


def test_sin_ninguna_corrida_registrada_tampoco():
    """Base recien instalada: no hay de que avisar."""
    db = FakeSession({"origen IN": []})
    assert errores_del_ultimo_barrido(db) is None


def test_los_errores_se_parsean_y_traen_el_nombre():
    db = FakeSession({
        "origen IN": [CON_ERROR],
        "name FROM Employee": [{"id": 8, "name": "Emiliano Rojo"}],
    })
    r = errores_del_ultimo_barrido(db)
    assert r["id"] == 109
    assert r["origen"] == "manual"
    assert r["procesados"] == 4
    assert r["errores"] == [{
        "employeeId": 8, "nombre": "Emiliano Rojo",
        "error": "TypeError: no se puede comparar",
    }]


def test_solo_mira_las_corridas_masivas_y_terminadas():
    """
    La regla que define la feature. Se afirma sobre el SQL y no sobre el
    resultado porque FakeSession devuelve lo que se le pida: lo unico que
    prueba que los barridos parciales quedan afuera es el filtro mismo.
    """
    db = FakeSession({"origen IN": []})
    errores_del_ultimo_barrido(db)
    sql = db.ejecutadas[0][0]
    assert "'nocturno'" in sql and "'manual'" in sql and "'arranque'" in sql
    assert "cupo_permiso" not in sql and "extension_tolerancia" not in sql
    assert "finalizadoAt IS NOT NULL" in sql


def test_un_json_malformado_no_tumba_la_pantalla():
    """
    La pantalla existe justamente para mostrar fallas: no puede fallar ella
    misma porque el registro de auditoria quedo corrupto.
    """
    db = FakeSession({"origen IN": [{**CON_ERROR, "errores": "esto no es json"}]})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"] == [
        {"employeeId": None, "nombre": None, "error": "esto no es json"},
    ]


def test_un_empleado_sin_nombre_se_muestra_igual():
    """Legajo borrado de la base: se muestra el numero pelado, no se oculta."""
    db = FakeSession({"origen IN": [CON_ERROR], "name FROM Employee": []})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"][0]["employeeId"] == 8
    assert r["errores"][0]["nombre"] is None


def test_una_entrada_sin_employeeId_se_muestra_igual():
    """Un error de la corrida entera, no atribuible a un empleado."""
    db = FakeSession({"origen IN": [
        {**CON_ERROR, "errores": '[{"error": "se cayo la conexion"}]'},
    ]})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"] == [
        {"employeeId": None, "nombre": None, "error": "se cayo la conexion"},
    ]


def test_sin_employeeIds_no_consulta_nombres():
    """Una vuelta a la base de mas cuando no hay a quien buscarle el nombre."""
    db = FakeSession({"origen IN": [
        {**CON_ERROR, "errores": '[{"error": "se cayo la conexion"}]'},
    ]})
    errores_del_ultimo_barrido(db)
    assert all("FROM Employee" not in sql for sql, _ in db.ejecutadas)
