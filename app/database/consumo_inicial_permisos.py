"""
Horas de permiso ya consumidas antes de que el sistema las registrara.

El cupo anual sale de la jornada laboral y se consume cronologicamente. Un
empleado recien dado de alta -o al que recien se le asigna una jornada- no
tiene ninguna fila de Permission del anio, asi que arranca con el cupo entero
aunque en la realidad ya se haya tomado horas que se llevaban en papel.

Cada carga de RRHH es un ASIENTO: varias del mismo empleado y anio se suman.
Cargar 5 y despues 10 da 15, no 10 -son dos cargas reales, no una correccion
de la otra. Un asiento equivocado se corrige borrandolo, que es la
contrapartida necesaria: sumando, un 50 mal tipeado quedaria para siempre.

Se guarda lo CONSUMIDO y no lo que le queda, al reves que SaldoInicialLicencia.
Es deliberado: el cupo de permisos no se deriva de nada, sale de
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
    cargadoEn       DATETIME2    NOT NULL
);
"""

# La primera version de la tabla tenia UNIQUE (employeeId, anio), porque cada
# carga reemplazaba a la anterior. Ahora cada carga es un asiento y varios del
# mismo par son el caso normal, asi que el constraint tiene que irse. Las bases
# que ya lo tienen lo sueltan aca; las nuevas no lo crean nunca.
DROP_UQ_SQL = """
IF EXISTS (SELECT 1 FROM sys.objects
           WHERE name = 'UQ_ConsumoInicialPermiso_emp_anio'
             AND parent_object_id = OBJECT_ID('ConsumoInicialPermiso'))
ALTER TABLE ConsumoInicialPermiso
    DROP CONSTRAINT UQ_ConsumoInicialPermiso_emp_anio;
"""


def ensure_table(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()
    db.execute(text(DROP_UQ_SQL))
    db.commit()


def total_de_empleado(db: Session, employee_id: int,
                      anio: int) -> float | None:
    """
    La suma de los asientos de ese empleado y anio, o None si no hay ninguno.

    NO coalesce a 0 a proposito: sus dos consumidores necesitan cosas
    distintas. El recalculo hace la aritmetica y coalesce con `or 0.0`, porque
    sin carga el banco es el cupo completo. El endpoint conserva la
    distincion, porque el panel de RRHH muestra el estado real: no haber
    mirado a un empleado y haber determinado que no uso ninguna hora son cosas
    distintas. Si coalesciera aca, esa distincion se perderia en la capa de
    datos y no habria forma de recuperarla.

    El SUM va en la consulta y no en Python: traer todas las filas para
    sumarlas aca seria leer de mas para tirar.
    """
    fila = db.execute(
        text("""
            SELECT SUM(horasConsumidas) AS total
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().first()
    if fila is None or fila["total"] is None:
        return None
    return float(fila["total"])


def asientos_de_empleado(db: Session, employee_id: int,
                         anio: int) -> list[dict]:
    """
    Los asientos de ese empleado y anio, el mas nuevo primero.

    Incluye el id porque es lo que el panel necesita para poder borrar uno
    puntual, que es la unica forma de corregir una carga equivocada.
    """
    filas = db.execute(
        text("""
            SELECT id, horasConsumidas, cargadoPor, cargadoEn
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
            ORDER BY cargadoEn DESC, id DESC
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().all()
    return [dict(f) for f in filas]


def agregar_asiento(db: Session, employee_id: int, anio: int,
                    horas: float, cargado_por: int | None) -> None:
    """
    Agrega un asiento. Es INSERT y no MERGE: la segunda carga del mismo
    (empleado, anio) es un asiento mas, no una correccion de la primera.
    """
    db.execute(
        text("""
            INSERT INTO ConsumoInicialPermiso
                (employeeId, anio, horasConsumidas, cargadoPor, cargadoEn)
            VALUES (:empId, :anio, :horas, :cargadoPor, GETDATE())
        """),
        {"empId": employee_id, "anio": anio, "horas": horas,
         "cargadoPor": cargado_por},
    )
    db.commit()


def borrar_asiento(db: Session, employee_id: int, asiento_id: int) -> bool:
    """
    Borra un asiento. Devuelve False si no existe o no es de ese empleado.

    El filtro por employeeId no es redundante con el id: sin el, el id que
    viene en la URL alcanzaria para borrarle un asiento a cualquier otra
    persona.
    """
    resultado = db.execute(
        text("""
            DELETE FROM ConsumoInicialPermiso
            WHERE id = :asientoId AND employeeId = :empId
        """),
        {"empId": employee_id, "asientoId": asiento_id},
    )
    db.commit()
    return resultado.rowcount > 0


# -- Compatibilidad transitoria --------------------------------------------
#
# carga_de_empleado / consumo_de_empleado / upsert_consumo quedan como lo
# estaban antes de esta tarea. Todavia los usan app/database/asistencia.py
# (mis_permisos), app/services/asistencia_recalc.py y
# app/routes/carga_inicial_permisos.py -ese ultimo es la Tarea 2, que no
# corresponde tocar aca. Se mantienen sin cambios para no romper esos
# consumidores antes de que esa tarea los migre a total_de_empleado /
# asientos_de_empleado / agregar_asiento. Con varios asientos reales estos
# tres dejan de ser exactos (leen o pisan una sola fila), pero eso ya era el
# comportamiento vigente para esos consumidores hasta que se actualicen.

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
