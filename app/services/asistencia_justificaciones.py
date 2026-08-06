"""
Reglas de la justificacion de ausencias que no tocan la base.

Vive aparte del SQL para poder testear la ventana sin TestClient ni base,
igual que validar_umbrales en asistencia_alertas.py.
"""

from datetime import date, timedelta

VENTANA_JUSTIFICACION_DIAS = 30


def validar_fecha_justificable(fecha: date, hoy: date) -> None:
    """
    Verifica que la fecha caiga dentro de la ventana para justificar. Lanza
    ValueError con un mensaje listo para mostrar; el traductor a HTTP vive en
    la capa de rutas.

    La ventana limita cuando se PUEDE crear una justificacion, nunca cuando
    aplica. Una vez cargada vale para siempre: si el motor mirara la ventana,
    el saldo historico de una persona cambiaria solo con el paso del tiempo.
    """
    if fecha > hoy:
        raise ValueError("No se puede justificar una fecha futura")
    if fecha < hoy - timedelta(days=VENTANA_JUSTIFICACION_DIAS):
        raise ValueError(
            f"Solo se pueden justificar ausencias de los ultimos "
            f"{VENTANA_JUSTIFICACION_DIAS} dias")
