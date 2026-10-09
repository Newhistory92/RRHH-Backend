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


def test_cupo_y_restante_son_null_para_un_anio_que_no_es_el_actual():
    """
    El cupo guardado es el vigente, no uno por anio: para un anio pasado no se
    sabe cual regia entonces. consumido y deuda si son datos historicos reales
    y se siguen mostrando.
    """
    anio_pasado = date.today().year - 1
    r = mis_permisos(_db(cupo=20.0, consumido=12.0, deuda=4.0), 8, anio_pasado)
    assert r["cupoAnual"] is None
    assert r["restante"] is None
    assert r["consumido"] == 12.0
    assert r["deuda"] == 4.0


def test_cupo_y_restante_se_muestran_para_el_anio_actual():
    r = mis_permisos(_db(cupo=20.0, consumido=12.0), 8, date.today().year)
    assert r["cupoAnual"] == 20.0
    assert r["restante"] == 8.0


def test_el_consumo_inicial_se_devuelve_y_descuenta_del_restante():
    """
    Las horas cargadas a mano no dejan filas en Permission ni en
    JornadaDiaria: si no se devolvieran, el restante quedaria inflado.
    """
    db = _db(cupo=12.0, consumido=2.0, deuda=0.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 5.0}]
    r = mis_permisos(db, 8, date.today().year)
    assert r["consumoInicial"] == 5.0
    # 12 de cupo, 5 cargadas a mano y 2 del sistema: quedan 5.
    assert r["restante"] == 5.0
    # consumido sigue siendo solo lo que registro el sistema: la pantalla las
    # muestra en lineas separadas para que el total cierre contra la lista.
    assert r["consumido"] == 2.0


def test_sin_carga_inicial_el_consumo_inicial_es_cero():
    r = mis_permisos(_db(cupo=12.0, consumido=2.0), 8, date.today().year)
    assert r["consumoInicial"] == 0.0
    assert r["restante"] == 10.0


def test_el_restante_no_baja_de_cero_con_la_carga_inicial():
    db = _db(cupo=12.0, consumido=2.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 20.0}]
    r = mis_permisos(db, 8, date.today().year)
    assert r["restante"] == 0.0


def test_el_consumo_inicial_es_null_para_un_anio_que_no_es_el_actual():
    """Misma regla que cupoAnual y restante: solo se muestra el anio en curso."""
    r = mis_permisos(_db(cupo=12.0), 8, date.today().year - 1)
    assert r["consumoInicial"] is None


def test_la_carga_inicial_que_supera_el_cupo_es_deuda_desde_que_se_carga():
    """
    Sin ningun permiso nuevo en el anio: si la carga inicial sola ya supera
    el cupo, esa persona ya se paso. No hay que esperar a que un permiso
    nuevo lo revele -sin esto, "A recuperar" mostraria 0 como si estuviera
    al dia.
    """
    db = _db(cupo=12.0, consumido=0.0, deuda=0.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 25.0}]
    r = mis_permisos(db, 8, date.today().year)
    assert r["restante"] == 0.0
    # 25 cargadas contra 12 de cupo: 13 de excedente, nadie mas debe nada.
    assert r["deuda"] == 13.0


def test_el_excedente_de_la_carga_inicial_se_suma_a_la_deuda_del_sistema():
    """La deuda que ya traia el sistema y la del excedente no se pisan."""
    db = _db(cupo=12.0, consumido=0.0, deuda=3.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 20.0}]
    r = mis_permisos(db, 8, date.today().year)
    # 3 de deuda del sistema + 8 de excedente (20 - 12).
    assert r["deuda"] == 11.0


def test_una_carga_dentro_del_cupo_no_agrega_deuda():
    db = _db(cupo=12.0, consumido=0.0, deuda=0.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 5.0}]
    r = mis_permisos(db, 8, date.today().year)
    assert r["deuda"] == 0.0


def test_el_excedente_no_se_agrega_para_un_anio_que_no_es_el_actual():
    """El consumo inicial de un anio pasado no existe para mis_permisos: sin
    el, no hay excedente que calcular."""
    db = _db(cupo=12.0, consumido=0.0, deuda=0.0)
    db.respuestas["SUM(horasConsumidas)"] = [{"total": 25.0}]
    r = mis_permisos(db, 8, date.today().year - 1)
    assert r["deuda"] == 0.0
