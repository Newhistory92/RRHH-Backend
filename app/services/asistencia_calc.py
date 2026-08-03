"""
Motor de calculo de asistencia. Funcion pura: no toca la base de datos ni los
relojes, asi que toda la logica dificil -tolerancia y banco de permisos- se
testea sin fixtures.

La unidad de calculo es el dia. El arrastre del banco anual de permisos es
responsabilidad de calcular_anio, que recorre los dias en orden cronologico.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

BANCO_PERMISO_ANUAL_HORAS = 12.0

# weekday(): lunes=0 ... domingo=6
DIAS_HABILES = frozenset({0, 1, 2, 3, 4})

ESTADO_OK = "ok"
ESTADO_INCOMPLETA = "incompleta"
ESTADO_AUSENTE = "ausente"
ESTADO_FERIADO = "feriado"
ESTADO_LICENCIA = "licencia"
ESTADO_SIN_HORARIO = "sin_horario"


@dataclass(frozen=True)
class HorarioDia:
    """horaInicio y horaFin son decimales: 8.5 es las 08:30."""
    horaInicio: float
    horaFin: float
    horasTrabajo: float


@dataclass(frozen=True)
class Permiso:
    horas: float
    oficial: bool


@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    marcaciones: list[datetime]
    horario: Optional[HorarioDia]
    es_feriado: bool
    tiene_licencia: bool
    permisos: list[Permiso]
    entrada_manual: Optional[datetime]
    salida_manual: Optional[datetime]


@dataclass(frozen=True)
class ResultadoDia:
    fecha: date
    estado: str
    horasRequeridas: float
    horasTrabajadas: float
    saldoDia: float
    entrada: Optional[datetime]
    salida: Optional[datetime]
    permisoBanco: float
    permisoDeuda: float
    permisoOficial: float


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _extremos(e: EntradaDia) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Primera marcacion = entrada, ultima = salida (todos marcan en el mismo
    reloj). La carga manual de RRHH tiene prioridad sobre el dispositivo.
    """
    ordenadas = sorted(e.marcaciones)
    entrada = e.entrada_manual or (ordenadas[0] if ordenadas else None)
    salida = e.salida_manual
    if salida is None and len(ordenadas) >= 2:
        salida = ordenadas[-1]
    return entrada, salida


def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol_entrada_min: int, tol_salida_min: int) -> float:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol_entrada_min / 60
    tol_sal = tol_salida_min / 60

    if horario.horaInicio < ent <= horario.horaInicio + tol_ent:
        ent = horario.horaInicio
    if horario.horaFin - tol_sal <= sal < horario.horaFin:
        sal = horario.horaFin

    return sal - ent


def _sumar_permisos(permisos: list[Permiso]) -> tuple[float, float]:
    regular = sum(p.horas for p in permisos if not p.oficial)
    oficial = sum(p.horas for p in permisos if p.oficial)
    return regular, oficial


def calcular_dia(entrada_dia: EntradaDia, tol_entrada_min: int,
                 tol_salida_min: int,
                 banco_disponible: float) -> Optional[ResultadoDia]:
    """
    Devuelve la fila del dia, o None cuando no corresponde generar ninguna
    (fin de semana o feriado sin marcaciones).
    """
    e = entrada_dia
    entrada, salida = _extremos(e)
    hay_marcas = entrada is not None
    no_laborable = e.es_feriado or e.fecha.weekday() not in DIAS_HABILES

    # Dia no laborable: sin marcaciones no existe la fila; con marcaciones todo
    # lo trabajado es saldo a favor y no se aplica tolerancia, porque el
    # horario no rige un dia que no se debia trabajar.
    if no_laborable:
        if not hay_marcas or salida is None:
            return None
        trabajadas = _hora_decimal(salida) - _hora_decimal(entrada)
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_FERIADO,
            horasRequeridas=0.0, horasTrabajadas=trabajadas, saldoDia=trabajadas,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if e.tiene_licencia:
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_LICENCIA,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if e.horario is None:
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_SIN_HORARIO,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    permiso_regular, permiso_oficial = _sumar_permisos(e.permisos)
    permiso_banco = min(permiso_regular, max(banco_disponible, 0.0))
    permiso_deuda = permiso_regular - permiso_banco

    if not hay_marcas:
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_AUSENTE,
            horasRequeridas=e.horario.horasTrabajo, horasTrabajadas=0.0,
            saldoDia=-e.horario.horasTrabajo,
            entrada=None, salida=None,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if salida is None:
        # Marco un solo extremo. No se penaliza hasta que RRHH cargue el otro:
        # aparece en el tablero de incompletas con saldo neutro.
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_INCOMPLETA,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=None,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    brutas = _ajustar_por_tolerancia(
        entrada, salida, e.horario, tol_entrada_min, tol_salida_min,
    )
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return ResultadoDia(
        fecha=e.fecha, estado=ESTADO_OK,
        horasRequeridas=requeridas, horasTrabajadas=trabajadas,
        saldoDia=trabajadas - requeridas,
        entrada=entrada, salida=salida,
        permisoBanco=permiso_banco, permisoDeuda=permiso_deuda,
        permisoOficial=permiso_oficial,
    )


def calcular_anio(dias: list[EntradaDia], tol_entrada_min: int,
                  tol_salida_min: int) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.
    """
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(
            d, tol_entrada_min, tol_salida_min,
            BANCO_PERMISO_ANUAL_HORAS - consumido,
        )
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
