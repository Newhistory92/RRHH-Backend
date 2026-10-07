"""
La lectura que alimenta la pantalla "Mis permisos".

Lo importante que se testea aca: los totales se LEEN de JornadaDiaria, no se
recalculan. Una segunda implementacion de la regla cronologica se
desincronizaria del motor sin que nadie lo note.
"""

from datetime import date

from app.database.asistencia import mis_permisos
from tests.fakes import FakeSession


def _db(cupo=12.0, consumido=8.5, deuda=2.0, permisos=None, anios=None):
    # jornada_id refleja lo que el LEFT JOIN real devolveria: None solo
    # cuando no hay jornada (que es como estos tests simulan "sin jornada",
    # pasando cupo=None); en cualquier otro caso, un id real.
    jornada_id = None if cupo is None else 1
    return FakeSession({
        "FROM Employee e": [{"cupo": cupo, "jornada_id": jornada_id}],
        "FROM JornadaDiaria": [{"consumido": consumido, "deuda": deuda}],
        "ORDER BY date DESC": permisos if permisos is not None else [],
        "SELECT DISTINCT YEAR(date)": anios if anios is not None else [],
    })


def test_los_totales_salen_de_jornada_diaria():
    r = mis_permisos(_db(), 8, 2026)
    assert r["cupoAnual"] == 12.0
    assert r["consumido"] == 8.5
    assert r["deuda"] == 2.0
    assert r["restante"] == 3.5


def test_el_restante_no_baja_de_cero():
    """
    Si el consumido supera el cupo -posible si RRHH lo bajo despues de que la
    persona ya habia pedido permisos- el restante es 0, no un negativo que se
    leeria como deuda duplicada.
    """
    r = mis_permisos(_db(cupo=4.0, consumido=10.0), 8, 2026)
    assert r["restante"] == 0.0


def test_sin_jornada_el_cupo_es_cero():
    r = mis_permisos(_db(cupo=None, consumido=0.0, deuda=6.0), 8, 2026)
    assert r["cupoAnual"] == 0.0
    assert r["restante"] == 0.0
    assert r["deuda"] == 6.0


def test_los_permisos_se_serializan_con_la_fecha_en_iso():
    permisos = [{"id": 4, "date": date(2026, 3, 4), "exitTime": 10.5,
                 "returnTime": 12.0, "hours": 1.5, "oficial": False}]
    r = mis_permisos(_db(permisos=permisos), 8, 2026)
    assert r["permisos"] == [{
        "id": 4, "fecha": "2026-03-04", "exitTime": 10.5,
        "returnTime": 12.0, "horas": 1.5, "oficial": False,
    }]


def test_el_anio_en_curso_esta_siempre_en_el_selector():
    """
    Aunque no tenga ningun permiso: es el anio que la pantalla abre por
    defecto y tiene que poder mostrar el cupo completo sin consumir.
    """
    r = mis_permisos(_db(anios=[{"anio": 2024}]), 8, 2026)
    assert date.today().year in r["aniosConDatos"]
    assert 2024 in r["aniosConDatos"]
    # Mas nuevo primero: es el orden en que se quieren leer.
    assert r["aniosConDatos"] == sorted(r["aniosConDatos"], reverse=True)


def test_tiene_jornada_distingue_sin_jornada_de_cupo_cero_a_proposito():
    # Con jornada, cupo configurado en 0 a proposito.
    r = mis_permisos(_db(cupo=0.0, consumido=0.0, deuda=0.0), 8, 2026)
    assert r["tieneJornada"] is True
    assert r["cupoAnual"] == 0.0

    # Sin jornada: cupo None viene del LEFT JOIN sin fila.
    r2 = mis_permisos(_db(cupo=None, consumido=0.0, deuda=0.0), 8, 2026)
    assert r2["tieneJornada"] is False
    assert r2["cupoAnual"] == 0.0
