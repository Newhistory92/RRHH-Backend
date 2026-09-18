"""
Reglas de la baja que no tocan la base.

Vive aparte del SQL para poder testear las condiciones sin base ni
TestClient. baja_vigente es la definicion unica de "esta de baja", y la
comparten el recorte de permisos, el job diario y los dos cortes de computo
(vacaciones y asistencia): una sola regla para todos los caminos.
"""

from datetime import date, datetime
from typing import Optional

# Cerrado a proposito. Las estadisticas del tablero se leen sobre estas
# categorias, asi que tienen que ser estables y comparables entre anios;
# agregar un motivo es una linea aca y un deploy.
MOTIVOS_DE_BAJA: tuple[str, ...] = (
    "Jubilación",
    "Renuncia",
    "Despido",
    "Fin de contrato",
    "Fallecimiento",
    "Traslado a otro organismo",
    "Abandono de cargo",
)


def a_date(valor) -> Optional[date]:
    """
    Normaliza lo que devuelve pyodbc a un date limpio.

    datetime hereda de date, asi que hay que chequear el tipo mas especifico
    primero: el guard invertido ya rompio una vez en este repo.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor).split("T")[0])


def baja_vigente(bajas: list[dict], hoy: date) -> Optional[dict]:
    """
    La baja que hoy tiene efecto, o None.

    Dos casos no tienen efecto. Una baja con fechaReingreso: la persona
    volvio, y la fila queda solo como historial. Y una fechaBaja futura: RRHH
    la carga cuando la sabe y la persona sigue trabajando hasta ese dia.

    Si hubiera mas de una abierta -que el endpoint no permite- gana la mas
    reciente, para que el corte no dependa del orden en que vino la lista.
    """
    vigentes = []
    for b in bajas:
        if b.get("fechaReingreso") is not None:
            continue
        fecha = a_date(b.get("fechaBaja"))
        if fecha is not None and fecha <= hoy:
            vigentes.append((fecha, b))
    if not vigentes:
        return None
    return max(vigentes, key=lambda par: par[0])[1]


def baja_abierta(bajas: list[dict]) -> Optional[dict]:
    """
    La baja sin reingreso, tenga efecto o no, o None.

    Es la que cuenta para "una sola baja abierta por persona": una programada
    tambien la ocupa, y es la que RRHH puede cancelar antes de que llegue el
    dia. Si hubiera mas de una gana la mas reciente, como en baja_vigente.
    """
    abiertas = [b for b in bajas if b.get("fechaReingreso") is None]
    if not abiertas:
        return None
    return max(abiertas, key=lambda b: a_date(b.get("fechaBaja")) or date.min)


def antiguedad_en_anios(fecha_ingreso, fecha_hasta) -> Optional[float]:
    """
    Anios trabajados entre las dos fechas, con un decimal.

    None cuando falta alguna de las dos o cuando la baja es anterior al
    ingreso: no se devuelve cero, que en el tablero se leeria como "entro y se
    fue el mismo dia" en vez de "no sabemos".
    """
    ingreso = a_date(fecha_ingreso)
    hasta = a_date(fecha_hasta)
    if ingreso is None or hasta is None or hasta < ingreso:
        return None
    meses = (hasta.year - ingreso.year) * 12 + hasta.month - ingreso.month
    return round(meses / 12.0, 1)
