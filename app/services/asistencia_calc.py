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
    "Tolerancias", "AjusteTolerancia", "calcular_dia", "calcular_anio",
]


@dataclass(frozen=True)
class Tolerancias:
    entradaMin: int
    salidaMin: int
    estrictaEntradaMin: int
    estrictaSalidaMin: int


@dataclass(frozen=True)
class AjusteTolerancia:
    brutas: float
    entradaUsada: bool
    salidaUsada: bool
    abusoEntrada: bool
    abusoSalida: bool


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
    abusoEntrada: bool
    abusoSalida: bool
    entradaManual: bool
    salidaManual: bool


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol: Tolerancias) -> AjusteTolerancia:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.

    El segundo escalon marca el dia como abuso cuando la persona se quedo del
    lado perdonado pero paso el margen razonable. La condicion exige que la
    tolerancia se haya usado: a quien llega mas tarde ya se le descuentan las
    horas y marcarlo ademas seria penalizarlo dos veces.

    El desvio se compara en segundos enteros. En horas decimales el borde
    exacto quedaria a merced del error del float cuando el horario no arranca
    en hora redonda: 7.5 + 7/60 y 7 + 37/60 son la misma cantidad matematica
    pero no necesariamente el mismo float.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol.entradaMin / 60
    tol_sal = tol.salidaMin / 60

    uso_entrada = horario.horaInicio < ent <= horario.horaInicio + tol_ent
    uso_salida = horario.horaFin - tol_sal <= sal < horario.horaFin

    desvio_ent_seg = round((ent - horario.horaInicio) * 3600)
    desvio_sal_seg = round((horario.horaFin - sal) * 3600)

    abuso_entrada = uso_entrada and desvio_ent_seg > tol.estrictaEntradaMin * 60
    abuso_salida = uso_salida and desvio_sal_seg > tol.estrictaSalidaMin * 60

    if uso_entrada:
        ent = horario.horaInicio
    if uso_salida:
        sal = horario.horaFin

    return AjusteTolerancia(
        brutas=sal - ent,
        entradaUsada=uso_entrada, salidaUsada=uso_salida,
        abusoEntrada=abuso_entrada, abusoSalida=abuso_salida,
    )


def _sumar_permisos(permisos: list[Permiso]) -> tuple[float, float]:
    regular = sum(p.horas for p in permisos if not p.oficial)
    oficial = sum(p.horas for p in permisos if p.oficial)
    return regular, oficial


def _resultado(e: EntradaDia, estado: str, requeridas: float, trabajadas: float,
               saldo: float, banco: float = 0.0, deuda: float = 0.0,
               oficial: float = 0.0, tol_ent: bool = False,
               tol_sal: bool = False,
               abuso_ent: bool = False, abuso_sal: bool = False) -> ResultadoDia:
    """Arma la fila arrastrando lo que ya venia resuelto en los extremos."""
    x = e.extremos
    return ResultadoDia(
        fecha=e.fecha, estado=estado,
        horasRequeridas=requeridas, horasTrabajadas=trabajadas, saldoDia=saldo,
        entrada=x.entrada, salida=x.salida,
        permisoBanco=banco, permisoDeuda=deuda, permisoOficial=oficial,
        incidencias=x.incidencias,
        toleranciaEntradaUsada=tol_ent, toleranciaSalidaUsada=tol_sal,
        abusoEntrada=abuso_ent, abusoSalida=abuso_sal,
        entradaManual=x.entrada_manual, salidaManual=x.salida_manual,
    )


def calcular_dia(entrada_dia: EntradaDia, tolerancias: Tolerancias,
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

    ajuste = _ajustar_por_tolerancia(entrada, salida, e.horario, tolerancias)
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = ajuste.brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return _resultado(
        e, ESTADO_OK, requeridas, trabajadas, trabajadas - requeridas,
        banco=permiso_banco, deuda=permiso_deuda, oficial=permiso_oficial,
        tol_ent=ajuste.entradaUsada, tol_sal=ajuste.salidaUsada,
        abuso_ent=ajuste.abusoEntrada, abuso_sal=ajuste.abusoSalida,
    )


def calcular_anio(dias: list[EntradaDia],
                  tolerancias: Tolerancias) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.
    """
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(d, tolerancias, BANCO_PERMISO_ANUAL_HORAS - consumido)
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
