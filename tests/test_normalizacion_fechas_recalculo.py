"""
Las columnas datetime2 de la base tienen que llegar al motor como date.

El repo ya conocia esta trampa -el docstring de _a_date la nombra-: datetime
HEREDA de date, asi que `isinstance(valor, date)` es True tambien para un
datetime y el guard invertido `x if isinstance(x, date) else x.date()` nunca
convierte nada.

Rompio de verdad: License.startDate/endDate y Permission.date son datetime2.
El recalculo del empleado 8 murio todos los dias desde el 2026-10-09 con
"'>' not supported between instances of 'datetime.date' and 'datetime.datetime'"
-su licencia del 8 al 14 de octubre recien entro en la ventana ese dia- y su
asistencia dejo de aparecer. Los permisos, por su lado, fallaban callados: el
diccionario quedaba indexado por datetime y el motor lo consulta por date, asi
que ningun permiso llegaba nunca al calculo del dia.
"""

from datetime import date, datetime

from app.routes.asistencia_ausencias import _licencia_que_cubre
from app.services.asistencia_recalc import (
    _dias_con_licencia, _feriados, _permisos_por_dia,
)
from tests.fakes import FakeSession


def test_una_licencia_datetime_no_tumba_el_recalculo():
    """
    El caso que rompio en produccion: max(datetime, date) explota.

    Sin la normalizacion esto no devuelve mal, directamente levanta TypeError
    y se lleva puesto el recalculo entero del empleado.
    """
    db = FakeSession({"FROM License": [{
        "startDate": datetime(2026, 10, 8, 3, 0),
        "endDate": datetime(2026, 10, 14, 3, 0),
    }]})
    dias = _dias_con_licencia(db, 8, date(2026, 10, 1), date(2026, 10, 31))
    assert date(2026, 10, 9) in dias
    assert all(type(d) is date for d in dias)


def test_la_licencia_se_recorta_al_rango_pedido():
    """La normalizacion no puede cambiar el recorte que ya hacia."""
    db = FakeSession({"FROM License": [{
        "startDate": datetime(2026, 10, 8, 3, 0),
        "endDate": datetime(2026, 10, 14, 3, 0),
    }]})
    dias = _dias_con_licencia(db, 8, date(2026, 10, 10), date(2026, 10, 12))
    assert dias == {date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)}


def test_los_permisos_quedan_indexados_por_date():
    """
    El fallo callado: con la clave en datetime, el permisos.get(dia) del
    recalculo -que busca por date- no encuentra nada nunca, y el permiso se
    ignora en el calculo del dia sin un solo error en el log.
    """
    db = FakeSession({"FROM Permission": [
        {"date": datetime(2026, 6, 30, 0, 0), "hours": 2.0, "oficial": False},
    ]})
    por_dia = _permisos_por_dia(db, 3, date(2026, 1, 1), date(2026, 12, 31))
    assert date(2026, 6, 30) in por_dia
    assert por_dia[date(2026, 6, 30)][0].horas == 2.0


def test_los_feriados_quedan_indexados_por_date():
    """
    Feriado.fecha hoy es DATE y no sufre la trampa, pero el guard invertido
    es el mismo: si alguna vez la columna pasa a datetime, el motor dejaria de
    reconocer los feriados en silencio.
    """
    db = FakeSession({"FROM Feriado": [{"fecha": datetime(2026, 1, 1, 0, 0)}]})
    assert _feriados(db, date(2026, 1, 1), date(2026, 12, 31)) == {date(2026, 1, 1)}


def test_un_date_puro_pasa_intacto():
    """La normalizacion no puede romper lo que ya venia bien."""
    db = FakeSession({"FROM Feriado": [{"fecha": date(2026, 5, 1)}]})
    assert _feriados(db, date(2026, 1, 1), date(2026, 12, 31)) == {date(2026, 5, 1)}


# -- La misma trampa en la pantalla de Ausencias -------------------------------

def test_la_licencia_pendiente_que_cubre_el_dia_no_tumba_las_ausencias():
    """
    Segundo lugar donde el mismo guard invertido estaba activo: aca compara
    `ini <= dia <= fin` contra un date, asi que con una licencia sin aprobar
    que cubriera el dia, la pantalla de Ausencias levantaba TypeError.
    """
    licencias = [{
        "id": 3, "type": "Vacaciones", "status": "Pendiente",
        "startDate": datetime(2026, 10, 8, 3, 0),
        "endDate": datetime(2026, 10, 14, 3, 0),
    }]
    cubre = _licencia_que_cubre(licencias, date(2026, 10, 9))
    assert cubre == {"id": 3, "type": "Vacaciones", "status": "Pendiente"}


def test_una_licencia_que_no_cubre_el_dia_sigue_devolviendo_none():
    licencias = [{
        "id": 3, "type": "Vacaciones", "status": "Pendiente",
        "startDate": datetime(2026, 10, 8, 3, 0),
        "endDate": datetime(2026, 10, 14, 3, 0),
    }]
    assert _licencia_que_cubre(licencias, date(2026, 10, 20)) is None
