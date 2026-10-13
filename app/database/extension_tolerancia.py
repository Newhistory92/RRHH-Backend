"""
Extensiones de tolerancia por dia.

Un dia excepcional -un temporal, un paro de transporte- no le pega igual a
todos: quien vive fuera del anillo de Circunvalacion viaja mucho mas. RRHH
carga aca que tolerancia rige ese dia, y aplica solo a los marcados con
Employee.fueraAnilloCircunvalacion.

El valor REEMPLAZA los 15 minutos, no se suma: lo que RRHH ve en pantalla es
el numero final que va a regir.

Una fila por fecha. Es una propiedad del dia, no un libro de asientos que se
acumula, y por eso la clave unica: un segundo alta para la misma fecha se
rechaza en vez de pisar en silencio un valor que le perdona horas a media
planta.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.bajas import a_date

CREATE_TABLE_SQL = """
IF OBJECT_ID('ExtensionTolerancia', 'U') IS NULL
CREATE TABLE ExtensionTolerancia (
    id                   INT IDENTITY(1,1) PRIMARY KEY,
    fecha                DATE      NOT NULL,
    toleranciaEntradaMin INT       NOT NULL,
    toleranciaSalidaMin  INT       NULL,
    cargadoPor           INT       NULL,
    cargadoEn            DATETIME2 NOT NULL,
    CONSTRAINT UQ_ExtensionTolerancia_fecha UNIQUE (fecha)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def listar(db: Session) -> list[dict]:
    """Todas las extensiones, la mas nueva primero."""
    filas = db.execute(text("""
        SELECT id, fecha, toleranciaEntradaMin, toleranciaSalidaMin,
               cargadoPor, cargadoEn
        FROM ExtensionTolerancia
        ORDER BY fecha DESC
    """)).mappings().all()
    return [dict(f) for f in filas]


def extensiones_por_fecha(db: Session, desde: date,
                          hasta: date) -> dict[date, dict]:
    """
    Las extensiones del rango, indexadas por fecha.

    Indexado y no una lista porque el recalculo resuelve dia por dia: con el
    diccionario cada dia es un lookup, y recorrer una lista por cada uno de
    los 365 dias seria cuadratico sin necesidad.
    """
    filas = db.execute(text("""
        SELECT fecha, toleranciaEntradaMin, toleranciaSalidaMin
        FROM ExtensionTolerancia
        WHERE fecha >= :desde AND fecha <= :hasta
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return {
        a_date(f["fecha"]): {
            "toleranciaEntradaMin": int(f["toleranciaEntradaMin"]),
            "toleranciaSalidaMin": (None if f["toleranciaSalidaMin"] is None
                                    else int(f["toleranciaSalidaMin"])),
        }
        for f in filas
    }


def existe_para_fecha(db: Session, fecha: date) -> bool:
    """Si ya hay una extension cargada para ese dia."""
    fila = db.execute(text("""
        SELECT id FROM ExtensionTolerancia WHERE fecha = :fecha
    """), {"fecha": fecha}).mappings().first()
    return fila is not None


def agregar(db: Session, fecha: date, entrada_min: int,
            salida_min: int | None, cargado_por: int | None) -> None:
    """Da de alta la extension de un dia."""
    db.execute(text("""
        INSERT INTO ExtensionTolerancia
            (fecha, toleranciaEntradaMin, toleranciaSalidaMin,
             cargadoPor, cargadoEn)
        VALUES (:fecha, :entradaMin, :salidaMin, :cargadoPor, GETDATE())
    """), {"fecha": fecha, "entradaMin": entrada_min,
           "salidaMin": salida_min, "cargadoPor": cargado_por})
    db.commit()


def borrar(db: Session, extension_id: int) -> date | None:
    """
    Borra una extension y devuelve la fecha que tenia, o None si no existia.

    Devuelve la fecha -y no un bool- porque el caller necesita saber que anio
    recalcular: una extension de diciembre borrada ya entrado enero pertenece
    a diciembre, no al anio en curso. OUTPUT lo trae en la misma sentencia,
    sin un SELECT antes que dejaria una ventana entre leer y borrar.
    """
    fila = db.execute(text("""
        DELETE FROM ExtensionTolerancia
        OUTPUT deleted.fecha
        WHERE id = :id
    """), {"id": extension_id}).mappings().first()
    db.commit()
    if fila is None:
        return None
    return a_date(fila["fecha"])
