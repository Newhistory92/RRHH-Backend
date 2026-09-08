"""
Saldo de licencias pendiente al momento del alta de un empleado.

El saldo se calcula como dias que corresponden menos consumidos, y el consumo
sale solo de licencias que tramito este sistema. Un empleado cargado hoy no
tiene ninguna, asi que su consumo da cero y el sistema le muestra las
vacaciones completas de la ventana aunque ya se las haya tomado.

Esta tabla guarda lo que RRHH sabe del legajo: cuantos dias le quedan de cada
anio. Guarda el pendiente y no el consumo derivado porque para Vacaciones el
total se recalcula en cada consulta segun la antiguedad actual: el consumo
quedaria congelado mientras el total se mueve, y el saldo se desviaria solo al
cruzar un tramo de antiguedad.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('SaldoInicialLicencia', 'U') IS NULL
CREATE TABLE SaldoInicialLicencia (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    employeeId     INT           NOT NULL,
    anio           INT           NOT NULL,
    categoria      NVARCHAR(100) NOT NULL,
    diasPendientes INT           NOT NULL,
    cargadoPor     INT           NULL,
    cargadoEn      DATETIME2     NOT NULL,
    CONSTRAINT UQ_SaldoInicialLicencia_emp_anio_cat
        UNIQUE (employeeId, anio, categoria)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def saldos_de_empleado(db: Session, employee_id: int) -> dict[tuple[int, str], int]:
    """
    Lo cargado para un empleado, indexado por (anio, categoria).

    Que una clave NO aparezca significa "no se cargo nada", que es un estado
    distinto de "se cargo cero": la primera deja que rija el calculo normal
    del sistema, la segunda afirma que no le queda ningun dia.
    """
    filas = db.execute(
        text("""
            SELECT anio, categoria, diasPendientes
            FROM SaldoInicialLicencia
            WHERE employeeId = :empId
        """),
        {"empId": employee_id},
    ).mappings().all()
    return {(f["anio"], f["categoria"]): int(f["diasPendientes"]) for f in filas}


def upsert_saldos(
    db: Session,
    employee_id: int,
    filas: list[dict],
    cargado_por: int | None,
) -> int:
    """
    Guarda una tanda de saldos.

    Cada fila es {"anio", "categoria", "diasPendientes"}. Es MERGE y no INSERT
    porque corregir una carga equivocada es el caso normal y la clave
    (employeeId, anio, categoria) es unica; sin esto quedarian filas
    contradictorias para la misma celda.

    HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    simultaneas de la misma clave entrando las dos por NOT MATCHED.
    """
    if not filas:
        return 0

    db.execute(
        text("""
            MERGE SaldoInicialLicencia WITH (HOLDLOCK) AS destino
            USING (SELECT :empId AS employeeId,
                          :anio AS anio,
                          :categoria AS categoria) AS origen
                ON destino.employeeId = origen.employeeId
               AND destino.anio = origen.anio
               AND destino.categoria = origen.categoria
            WHEN MATCHED THEN
                UPDATE SET diasPendientes = :diasPendientes,
                           cargadoPor = :cargadoPor,
                           cargadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (employeeId, anio, categoria, diasPendientes,
                        cargadoPor, cargadoEn)
                VALUES (:empId, :anio, :categoria, :diasPendientes,
                        :cargadoPor, GETDATE());
        """),
        [
            {
                "empId": employee_id,
                "anio": f["anio"],
                "categoria": f["categoria"],
                "diasPendientes": f["diasPendientes"],
                "cargadoPor": cargado_por,
            }
            for f in filas
        ],
    )
    db.commit()
    return len(filas)
