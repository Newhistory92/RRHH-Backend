"""
Horas de permiso ya consumidas antes de que el sistema las registrara.

El cupo anual sale de la jornada laboral y se consume cronologicamente. Un
empleado recien dado de alta -o al que recien se le asigna una jornada- no
tiene ninguna fila de Permission del anio, asi que arranca con el cupo entero
aunque en la realidad ya se haya tomado horas que se llevaban en papel.

Esta tabla guarda lo que RRHH sabe: cuantas horas ya uso ese anio. Guarda lo
CONSUMIDO y no lo que le queda, al reves que SaldoInicialLicencia. Es
deliberado: el cupo de permisos no se deriva de nada, sale de
JornadaLaboral.horasPermisoAnual, que RRHH edita a mano. Guardando "le quedan
7", subir el cupo de 12 a 20 dejaria esas 7 clavadas cuando la persona uso 5 y
deberia tener 15. Lo consumido no se mueve; el cupo si.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('ConsumoInicialPermiso', 'U') IS NULL
CREATE TABLE ConsumoInicialPermiso (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    employeeId      INT          NOT NULL,
    anio            INT          NOT NULL,
    horasConsumidas DECIMAL(6,2) NOT NULL,
    cargadoPor      INT          NULL,
    cargadoEn       DATETIME2    NOT NULL,
    CONSTRAINT UQ_ConsumoInicialPermiso_emp_anio UNIQUE (employeeId, anio)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def carga_de_empleado(db: Session, employee_id: int, anio: int) -> dict | None:
    """
    La fila completa de ese empleado y anio, o None si no se cargo nada.

    El anio es parte de la clave y no un detalle: sin el, la carga de un anio
    seguiria descontando contra el cupo del siguiente.
    """
    fila = db.execute(
        text("""
            SELECT horasConsumidas, cargadoPor, cargadoEn
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().first()
    return dict(fila) if fila else None


def consumo_de_empleado(db: Session, employee_id: int,
                        anio: int) -> float | None:
    """
    Las horas ya consumidas, o None cuando no hay fila.

    NO coalesce a 0 a proposito: sus dos consumidores necesitan cosas
    distintas. El recalculo hace la aritmetica y coalesce con `or 0.0`, porque
    sin carga el banco es el cupo entero. El endpoint conserva la distincion,
    porque el panel de RRHH muestra vacio o cero segun corresponda: no haber
    mirado a un empleado y haber determinado que no uso ninguna hora son cosas
    distintas. Si coalesciera aca, esa distincion se perderia en la capa de
    datos y no habria forma de recuperarla.
    """
    fila = carga_de_empleado(db, employee_id, anio)
    return float(fila["horasConsumidas"]) if fila else None


def upsert_consumo(db: Session, employee_id: int, anio: int,
                   horas: float, cargado_por: int | None) -> None:
    """
    Guarda las horas del anio, corrigiendo si ya habia una carga.

    Es MERGE y no INSERT porque corregir una carga equivocada es el caso
    normal y la clave (employeeId, anio) es unica: un INSERT fallaria en el
    segundo intento.

    HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    simultaneas de la misma clave entrando las dos por NOT MATCHED.
    """
    db.execute(
        text("""
            MERGE ConsumoInicialPermiso WITH (HOLDLOCK) AS destino
            USING (SELECT :empId AS employeeId, :anio AS anio) AS origen
                ON destino.employeeId = origen.employeeId
               AND destino.anio = origen.anio
            WHEN MATCHED THEN
                UPDATE SET horasConsumidas = :horas,
                           cargadoPor = :cargadoPor,
                           cargadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (employeeId, anio, horasConsumidas, cargadoPor, cargadoEn)
                VALUES (:empId, :anio, :horas, :cargadoPor, GETDATE());
        """),
        {"empId": employee_id, "anio": anio, "horas": horas,
         "cargadoPor": cargado_por},
    )
    db.commit()
