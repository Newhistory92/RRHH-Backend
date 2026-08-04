"""
Motor de calculo de asistencia. Funcion pura: no toca la base de datos ni los
relojes, asi que toda la logica dificil -tolerancia y banco de permisos- se
testea sin fixtures.

Recibe los extremos del dia ya interpretados por marcaciones_norm: aca no se
decide cual marca es la entrada, solo cuanto vale la jornada.

La unidad de calculo es el dia. El arrastre del banco anual de permisos es
responsabilidad de calcular_anio, que recorre los dias en orden cronologico.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from app.services.marcaciones_norm import ExtremosDia, HorarioDia

BANCO_PERMISO_ANUAL_HORAS = 12.0

# weekday(): lunes=0 ... domingo=6
DIAS_HABILES = frozenset({0, 1, 2, 3, 4})

ESTADO_OK = "ok"
ESTADO_INCOMPLETA = "incompleta"
ESTADO_AUSENTE = "ausente"
ESTADO_FERIADO = "feriado"
ESTADO_LICENCIA = "licencia"
ESTADO_SIN_HORARIO = "sin_horario"

# Re-export: los consumidores historicos importan HorarioDia desde aca.
__all__ = [
    "BANCO_PERMISO_ANUAL_HORAS", "DIAS_HABILES", "ESTADO_OK",
    "ESTADO_INCOMPLETA", "ESTADO_AUSENTE", "ESTADO_FERIADO", "ESTADO_LICENCIA",
    "ESTADO_SIN_HORARIO", "HorarioDia", "Permiso", "EntradaDia", "ResultadoDia",
    "calcular_dia", "calcular_anio",
]


@dataclass(frozen=True)
class Permiso:
    horas: float
    oficial: bool


@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    extremos: ExtremosDia
    horario: Optional[HorarioDia]
    es_feriado: bool
    tiene_licencia: bool
    permisos: list[Permiso]


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
    incidencias: tuple[str, ...]
    toleranciaEntradaUsada: bool
    toleranciaSalidaUsada: bool
    entradaManual: bool
    salidaManual: bool


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol_entrada_min: int,
                            tol_salida_min: int) -> tuple[float, bool, bool]:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.

    Devuelve las horas brutas y si cada tolerancia se aplico. Los dos flags se
    persisten para que el tablero pueda senalar el uso reiterado sin tener que
    recalcular la jornada.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol_entrada_min / 60
    tol_sal = tol_salida_min / 60

    uso_entrada = horario.horaInicio < ent <= horario.horaInicio + tol_ent
    if uso_entrada:
        ent = horario.horaInicio
    uso_salida = horario.horaFin - tol_sal <= sal < horario.horaFin
    if uso_salida:
        sal = horario.horaFin

    return sal - ent, uso_entrada, uso_salida


def _sumar_permisos(permisos: list[Permiso]) -> tuple[float, float]:
    regular = sum(p.horas for p in permisos if not p.oficial)
    oficial = sum(p.horas for p in permisos if p.oficial)
    return regular, oficial


def _resultado(e: EntradaDia, estado: str, requeridas: float, trabajadas: float,
               saldo: float, banco: float = 0.0, deuda: float = 0.0,
               oficial: float = 0.0, tol_ent: bool = False,
               tol_sal: bool = False) -> ResultadoDia:
    """Arma la fila arrastrando lo que ya venia resuelto en los extremos."""
    x = e.extremos
    return ResultadoDia(
        fecha=e.fecha, estado=estado,
        horasRequeridas=requeridas, horasTrabajadas=trabajadas, saldoDia=saldo,
        entrada=x.entrada, salida=x.salida,
        permisoBanco=banco, permisoDeuda=deuda, permisoOficial=oficial,
        incidencias=x.incidencias,
        toleranciaEntradaUsada=tol_ent, toleranciaSalidaUsada=tol_sal,
        entradaManual=x.entrada_manual, salidaManual=x.salida_manual,
    )


def calcular_dia(entrada_dia: EntradaDia, tol_entrada_min: int,
                 tol_salida_min: int,
                 banco_disponible: float) -> Optional[ResultadoDia]:
    """
    Devuelve la fila del dia, o None cuando no corresponde generar ninguna
    (fin de semana o feriado sin marcaciones).
    """
    e = entrada_dia
    entrada = e.extremos.entrada
    salida = e.extremos.salida
    no_laborable = e.es_feriado or e.fecha.weekday() not in DIAS_HABILES

    # Dia no laborable: sin marcaciones no existe la fila; con marcaciones todo
    # lo trabajado es saldo a favor y no se aplica tolerancia, porque el
    # horario no rige un dia que no se debia trabajar.
    if no_laborable:
        if entrada is None or salida is None:
            return None
        trabajadas = _hora_decimal(salida) - _hora_decimal(entrada)
        return _resultado(e, ESTADO_FERIADO, 0.0, trabajadas, trabajadas)

    if e.tiene_licencia:
        return _resultado(e, ESTADO_LICENCIA, 0.0, 0.0, 0.0)

    if e.horario is None:
        return _resultado(e, ESTADO_SIN_HORARIO, 0.0, 0.0, 0.0)

    permiso_regular, permiso_oficial = _sumar_permisos(e.permisos)
    permiso_banco = min(permiso_regular, max(banco_disponible, 0.0))
    permiso_deuda = permiso_regular - permiso_banco

    if entrada is None and salida is None:
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return _resultado(
            e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
            -e.horario.horasTrabajo,
        )

    if entrada is None or salida is None:
        # Falta un extremo. No se penaliza hasta que RRHH cargue el otro: el dia
        # queda neutro y visible en el tablero de incidencias.
        return _resultado(e, ESTADO_INCOMPLETA, 0.0, 0.0, 0.0)

    brutas, tol_ent, tol_sal = _ajustar_por_tolerancia(
        entrada, salida, e.horario, tol_entrada_min, tol_salida_min,
    )
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return _resultado(
        e, ESTADO_OK, requeridas, trabajadas, trabajadas - requeridas,
        banco=permiso_banco, deuda=permiso_deuda, oficial=permiso_oficial,
        tol_ent=tol_ent, tol_sal=tol_sal,
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
