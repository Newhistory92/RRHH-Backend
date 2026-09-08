"""
El saldo inicial dentro del endpoint de saldos.

Se prueba la funcion pura de armado, que es donde vive la decision. El
endpoint completo depende de seis consultas encadenadas y probarlo entero
mediria el andamiaje, no la regla.
"""

from app.routes.licenses import armar_balances


FILAS_CONFIG = [
    {"anio": 2026, "tipoLicencia": "Vacaciones", "contrato": "permanente",
     "diasTotales": 30, "diasConsumidos": 0},
]


def test_sin_saldo_inicial_vacaciones_usa_la_antiguedad():
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["diasTotales"] == 20
    assert balances[0]["disponibles"] == 20


def test_el_saldo_inicial_reemplaza_al_total():
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={(2026, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["diasTotales"] == 5
    assert balances[0]["disponibles"] == 5


def test_el_consumo_posterior_descuenta_del_saldo_inicial():
    """Cargado el saldo, el circuito comun sigue funcionando encima."""
    filas = [dict(FILAS_CONFIG[0], diasConsumidos=2)]
    balances = armar_balances(
        rows=filas, saldos_iniciales={(2026, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["disponibles"] == 3


def test_saldo_inicial_en_cero_no_otorga_dias():
    """Es el bug que motivo el trabajo: un cero leido como 'sin dato' le
    devolveria las vacaciones completas."""
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={(2026, "Vacaciones"): 0},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["disponibles"] == 0


def test_un_anio_sin_configuracion_aparece_si_tiene_saldo_cargado():
    """Solo existe configuracion de 2026: sin esto el saldo de 2024 quedaria
    guardado y seria invisible."""
    balances = armar_balances(
        rows=FILAS_CONFIG,
        saldos_iniciales={(2026, "Vacaciones"): 20, (2024, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    anios = {b["anio"] for b in balances}
    assert anios == {2024, 2026}
    fila_2024 = next(b for b in balances if b["anio"] == 2024)
    assert fila_2024["diasTotales"] == 5
    assert fila_2024["disponibles"] == 5


def test_nacimiento_no_se_le_ofrece_a_una_empleada():
    filas = [{"anio": 2026, "tipoLicencia": "Nacimiento", "contrato": "permanente",
              "diasTotales": 5, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Femenino", role_name="rrhh",
    )
    assert balances == []


def test_embarazo_no_se_le_ofrece_a_un_empleado():
    filas = [{"anio": 2026, "tipoLicencia": "Embarazo", "contrato": "permanente",
              "diasTotales": 90, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert balances == []


def test_las_licencias_restringidas_se_le_muestran_a_rrhh():
    """El rol llega en minuscula y se comparaba contra mayuscula, asi que la
    condicion era siempre verdadera y estas licencias estaban ocultas para
    todos, RRHH incluido."""
    filas = [{"anio": 2026, "tipoLicencia": "Accidente de trabajo",
              "contrato": "permanente", "diasTotales": 30, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert len(balances) == 1


def test_las_licencias_restringidas_no_se_le_muestran_a_un_empleado_comun():
    filas = [{"anio": 2026, "tipoLicencia": "Accidente de trabajo",
              "contrato": "permanente", "diasTotales": 30, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="user",
    )
    assert balances == []


def test_saldo_inicial_de_categoria_restringida_no_se_filtra_a_un_rol_comun():
    """El camino de 'sin configuracion' tiene que aplicar el mismo filtro que
    el camino normal, o una categoria restringida se filtra igual con solo
    cargarle un saldo inicial."""
    balances = armar_balances(
        rows=[], saldos_iniciales={(2026, "Accidente de trabajo"): 10},
        dias_vac=20, gender="Masculino", role_name="user",
    )
    assert balances == []


def test_saldo_inicial_de_categoria_restringida_se_muestra_a_rrhh():
    balances = armar_balances(
        rows=[], saldos_iniciales={(2026, "Accidente de trabajo"): 10},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert len(balances) == 1
    assert balances[0]["diasTotales"] == 10


def test_saldo_inicial_de_nacimiento_no_se_muestra_a_una_empleada():
    balances = armar_balances(
        rows=[], saldos_iniciales={(2026, "Nacimiento"): 5},
        dias_vac=20, gender="Femenino", role_name="rrhh",
    )
    assert balances == []
