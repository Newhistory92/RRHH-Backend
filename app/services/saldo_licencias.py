"""
Decisiones del saldo de licencias. Funciones puras, sin I/O.

Concentran tres reglas que antes vivian sueltas dentro del endpoint de saldos:
que total rige para un anio, que saldos cargados no tienen configuracion que
los muestre, y cual es la ventana de anios cargables.
"""

from datetime import date

# La ventana de carga: el anio calendario en curso y los dos anteriores.
# Coincide con el ciclo de expiracion de vacaciones; cargar algo mas viejo
# venceria en la primera corrida.
ANIOS_DE_VENTANA = 3

# El mes en que se habilitan las vacaciones del anio en curso.
MES_DE_CORTE = 10


def total_del_anio(
    saldo_inicial: int | None,
    es_vacaciones: bool,
    dias_vac: int,
    dias_totales: int,
) -> int:
    """
    Cuantos dias corresponden para un anio y categoria.

    El saldo cargado a mano gana sobre todo lo demas, incluido el cero: cero
    es una afirmacion de RRHH de que no le queda nada, no la ausencia de dato.
    La ausencia de dato es None, y recien ahi rige el calculo del sistema.
    """
    if saldo_inicial is not None:
        return saldo_inicial
    return dias_vac if es_vacaciones else dias_totales


def saldos_sin_configuracion(
    saldos_iniciales: dict[tuple[int, str], int],
    cubiertas: set[tuple[int, str]],
) -> list[tuple[int, str]]:
    """
    Las claves con saldo cargado que la configuracion no llego a mostrar.

    El armado de saldos recorre ConfiguracionLicencias, que hoy solo tiene
    filas de 2026: sin esto, un saldo cargado para 2024 quedaria guardado y
    seria invisible.
    """
    return sorted(clave for clave in saldos_iniciales if clave not in cubiertas)


def anios_de_carga(anio_actual: int) -> list[int]:
    """La ventana cargable, del mas nuevo al mas viejo."""
    return [anio_actual - i for i in range(ANIOS_DE_VENTANA)]


def ciclo_vacaciones(hoy: date) -> int:
    """
    Que anio de vacaciones rige en esta fecha.

    Las vacaciones de un anio se habilitan recien el 1 de octubre de ese
    anio: hasta entonces sigue rigiendo el saldo del anterior. Antes esta
    regla vivia como expresion suelta dentro del endpoint de saldos y no
    existia en el de tipos disponibles, que es el que de verdad limita
    cuantos dias se pueden pedir -- de ahi que los dos discreparan.
    """
    return hoy.year if hoy.month >= MES_DE_CORTE else hoy.year - 1


def anios_de_ventana(ciclo: int) -> list[int]:
    """La ventana vigente, del mas nuevo al mas viejo."""
    return [ciclo - i for i in range(ANIOS_DE_VENTANA)]


def expandir_por_anio(
    configs: list[dict],
    anios: list[int],
    consumidos_por_clave: dict[tuple[int, str], int],
) -> list[dict]:
    """
    Cruza la base de cada categoria con cada anio de la ventana.

    ConfiguracionLicencias guarda dias base por contrato y categoria, sin
    anio: los anios son una decision de codigo. Sin este cruce, un anio sin
    fila de configuracion simplemente no existia, que es de donde venia toda
    la familia de problemas de saldos invisibles.

    Devuelve la misma forma de fila que armar_balances ya consume.
    """
    return [
        {
            "anio": anio,
            "tipoLicencia": cfg["categoria"],
            "contrato": cfg["contrato"],
            "diasTotales": cfg["diasTotales"],
            "diasConsumidos": consumidos_por_clave.get(
                (anio, cfg["categoria"].lower()), 0
            ),
        }
        for anio in anios
        for cfg in configs
    ]
