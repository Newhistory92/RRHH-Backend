"""
La tolerancia puede variar por dia, y el motor no sabe por que.

calcular_anio recibe un diccionario fecha -> Tolerancias y aplica el que
corresponda. No sabe que existe una "extension" ni que es el anillo de
Circunvalacion: eso lo resuelve asistencia_recalc, que es el que habla con
la base.
"""

from datetime import date, datetime

from app.services import asistencia_calc as c
from app.services import marcaciones_norm as n

JORNADA_8H = n.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)
TOL = c.Tolerancias(entradaMin=15, salidaMin=15,
                    estrictaEntradaMin=7, estrictaSalidaMin=5)
# Un dia de extension: 30 minutos otorgados, y el margen estricto igualado al
# otorgado para que entrar dentro de lo concedido no deje marca de abuso.
TOL_EXTENDIDA = c.Tolerancias(entradaMin=30, salidaMin=15,
                              estrictaEntradaMin=30, estrictaSalidaMin=5)

MIERCOLES = date(2026, 7, 1)
JUEVES = date(2026, 7, 2)


def _dia(fecha, entrada_h, entrada_m):
    return c.EntradaDia(
        fecha=fecha,
        extremos=n.normalizar(
            [datetime(fecha.year, fecha.month, fecha.day, entrada_h, entrada_m),
             datetime(fecha.year, fecha.month, fecha.day, 16, 0)],
            JORNADA_8H, None,
        ),
        horario=JORNADA_8H, es_feriado=False, tiene_licencia=False,
        permisos=[],
    )


def test_sin_overrides_el_anio_calcula_igual_que_siempre():
    """La garantia de que esto no toca a nadie que no tenga el flag."""
    sin = c.calcular_anio([_dia(MIERCOLES, 8, 20)], TOL, 12.0)
    con_dict_vacio = c.calcular_anio([_dia(MIERCOLES, 8, 20)], TOL, 12.0, {})
    assert sin[0].saldoDia == con_dict_vacio[0].saldoDia
    assert sin[0].abusoEntrada == con_dict_vacio[0].abusoEntrada


def test_el_dia_con_override_usa_la_tolerancia_extendida():
    """Entrar 8:25 con 30 min otorgados no descuenta nada."""
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 25)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_el_dia_con_override_no_marca_abuso():
    """
    El motivo de igualar el margen estricto al otorgado: sin eso, todo el
    que llega 8:08 o despues quedaria marcado como abuso justo el dia que
    RRHH le dio el permiso.
    """
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 25)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.abusoEntrada is False


def test_pasarse_de_la_tolerancia_extendida_si_descuenta():
    """La extension corre el limite, no lo elimina."""
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 40)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.saldoDia < 0


def test_un_dia_sin_override_en_un_anio_que_tiene_otros_usa_la_normal():
    """El override es por fecha, no por anio."""
    miercoles, jueves = c.calcular_anio(
        [_dia(MIERCOLES, 8, 25), _dia(JUEVES, 8, 25)], TOL, 12.0,
        {MIERCOLES: TOL_EXTENDIDA},
    )
    assert miercoles.saldoDia == 0.0
    # El jueves no tiene extension: 25 minutos pasan los 15 de siempre.
    assert jueves.saldoDia < 0


# -- El cableado, con FakeSession -----------------------------------------------

from app.services import asistencia_recalc as r
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db_recalc(fuera_del_anillo, extensiones):
    return FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": 12.0,
            "fueraAnilloCircunvalacion": fuera_del_anillo,
        }],
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "FROM EmployeeBaja": [],
        "SUM(horasConsumidas)": [{"total": None}],
        "AS excedente": [{"excedente": 0.0}],
        "FROM ExtensionTolerancia": extensiones,
    })


def _overrides_usados(monkeypatch, db):
    """Corre recalcular_anio y devuelve el dict que recibio el motor."""
    capturado = {}

    def fake(dias, tolerancias, banco_anual, tolerancias_por_fecha=None):
        capturado["por_fecha"] = tolerancias_por_fecha
        return []

    monkeypatch.setattr(r, "calcular_anio", fake)
    r.recalcular_anio(db, 8, 2026, hoy=HOY)
    return capturado["por_fecha"]


def test_un_empleado_sin_el_flag_no_recibe_ningun_override(monkeypatch):
    """Con extensiones cargadas en la base, al no marcado no le aplican."""
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=False, extensiones=extensiones)
    assert _overrides_usados(monkeypatch, db) == {}


def test_un_empleado_con_el_flag_recibe_el_override_del_dia(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    overrides = _overrides_usados(monkeypatch, db)
    tol = overrides[date(2026, 7, 1)]
    assert tol.entradaMin == 30
    # El margen estricto igualado al otorgado: asi no marca abuso.
    assert tol.estrictaEntradaMin == 30


def test_la_salida_sin_cargar_queda_en_los_15_de_config(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    tol = _overrides_usados(monkeypatch, db)[date(2026, 7, 1)]
    assert tol.salidaMin == 15
    # Y su margen estricto sigue siendo el de siempre: la salida no se
    # extendio, asi que ahi el abuso tiene que poder marcarse igual.
    assert tol.estrictaSalidaMin == 5


def test_la_salida_cargada_tambien_iguala_su_margen_estricto(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": 20}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    tol = _overrides_usados(monkeypatch, db)[date(2026, 7, 1)]
    assert tol.salidaMin == 20
    assert tol.estrictaSalidaMin == 20
