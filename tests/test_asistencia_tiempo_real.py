"""
Tests del recalculo de tiempo real: la seleccion de a quien recalcular.

El calculo en si ya lo cubre test_asistencia_calc; aca lo que importa es que
recalcular_marcados elija los (empleado, anio) correctos, delegue en
recalcular_anio -el camino completo- y no tumbe la corrida cuando uno falla.
"""

from datetime import datetime, timedelta

from tests.fakes import FakeSession

from app.services import asistencia_recalc as r

FRAGMENTO_MARCADOS = "FROM Marcacion m"


def _sesion(pares: list[dict]) -> FakeSession:
    return FakeSession({FRAGMENTO_MARCADOS: pares})


# -- Seleccion de empleados ---------------------------------------------------

def test_devuelve_los_pares_empleado_anio_de_las_marcaciones_nuevas():
    db = _sesion([{"employeeId": 13, "anio": 2026},
                  {"employeeId": 21, "anio": 2026}])
    pares = r.empleados_con_marcaciones_nuevas(db, datetime(2026, 8, 28, 7, 0))
    assert pares == [(13, 2026), (21, 2026)]


def test_la_consulta_filtra_por_createdAt_y_no_por_fechaHora():
    """
    Lo que dispara el recalculo es que la fila sea nueva para nosotros, no
    cuando ficho la persona: un backlog viejo que entra hoy tiene que entrar.
    """
    db = _sesion([])
    r.empleados_con_marcaciones_nuevas(db, datetime(2026, 8, 28, 7, 0))
    sql = db.sql_ejecutado()
    assert "m.createdAt >= :desde" in sql
    assert "YEAR(m.fechaHora)" in sql


def test_sin_marcaciones_nuevas_no_recalcula_a_nadie(monkeypatch):
    llamadas = []
    monkeypatch.setattr(r, "recalcular_anio",
                        lambda db, eid, anio: llamadas.append((eid, anio)) or 0)
    db = _sesion([])
    resultado = r.recalcular_marcados(db)
    assert llamadas == []
    assert resultado == {"procesados": 0, "filas": 0, "errores": []}


# -- Delegacion en el calculo completo ----------------------------------------

def test_recalcula_el_anio_completo_de_cada_empleado_que_ficho(monkeypatch):
    """
    La clave del diseno: delega en recalcular_anio, que recomputa desde el 1
    de enero. Sin eso el banco anual de permisos arrancaria de cero cada vez.
    """
    llamadas = []

    def fake(db, eid, anio):
        llamadas.append((eid, anio))
        return 5

    monkeypatch.setattr(r, "recalcular_anio", fake)
    db = _sesion([{"employeeId": 13, "anio": 2026},
                  {"employeeId": 21, "anio": 2025}])
    resultado = r.recalcular_marcados(db)

    assert llamadas == [(13, 2026), (21, 2025)]
    assert resultado["procesados"] == 2
    assert resultado["filas"] == 10


def test_un_empleado_que_falla_no_aborta_a_los_demas(monkeypatch):
    def fake(db, eid, anio):
        if eid == 13:
            raise RuntimeError("horario invalido")
        return 3

    monkeypatch.setattr(r, "recalcular_anio", fake)
    db = _sesion([{"employeeId": 13, "anio": 2026},
                  {"employeeId": 21, "anio": 2026}])
    resultado = r.recalcular_marcados(db)

    assert resultado["procesados"] == 1
    assert resultado["filas"] == 3
    assert len(resultado["errores"]) == 1
    assert resultado["errores"][0]["employeeId"] == 13
    assert db.rollbacks == 1


# -- Ventana de deteccion -----------------------------------------------------

def test_la_ventana_se_solapa_con_el_intervalo_del_scheduler():
    """
    Mas ancha que los 5 min del tick: si una corrida se atrasa unos segundos,
    la marcacion la levanta la siguiente en vez de esperar al nocturno.
    """
    from app import scheduler

    assert r.VENTANA_TIEMPO_REAL_MIN > scheduler.INTERVALO_MINUTOS


def test_la_ventana_se_mide_hacia_atras_desde_ahora(monkeypatch):
    capturado = {}

    def fake(db, desde):
        capturado["desde"] = desde
        return []

    monkeypatch.setattr(r, "empleados_con_marcaciones_nuevas", fake)
    r.recalcular_marcados(_sesion([]), minutos=10)

    esperado = datetime.now() - timedelta(minutes=10)
    assert abs((capturado["desde"] - esperado).total_seconds()) < 5


# -- Auditoria ----------------------------------------------------------------

def test_no_abre_un_recalculo_en_el_log_de_auditoria(monkeypatch):
    """
    ~288 corridas por dia taparian los recalculos manuales y nocturnos, que
    son los que sirven para auditar.
    """
    monkeypatch.setattr(r, "recalcular_anio", lambda db, eid, anio: 1)
    db = _sesion([{"employeeId": 13, "anio": 2026}])
    r.recalcular_marcados(db)
    assert "RecalculoLog" not in db.sql_ejecutado()
