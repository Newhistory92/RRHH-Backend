"""
Persistencia de las bajas de empleados.

La tabla EmployeeBaja es la fuente de verdad. Employee.status es cache
cosmetico para los listados que ya muestran esa columna: la condicion real se
calcula con baja_vigente cada vez que se usa, asi que el cache no puede
desincronizar nada importante.

User.activo NO se toca en ningun camino de este modulo. Ese campo es el
bloqueo de cuenta del panel de ADMIN, que es un caso distinto: el dado de baja
conserva el acceso, recortado a su legajo.
"""

from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.estado_empleado import estado_segun_licencias
from app.services.bajas import a_date, antiguedad_en_anios, baja_abierta, baja_vigente

ESTADO_BAJA = "Baja"

CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'EmployeeBaja' AND xtype = 'U'
)
BEGIN
    CREATE TABLE EmployeeBaja (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        employeeId     INT            NOT NULL,
        motivo         NVARCHAR(50)   NOT NULL,
        fechaBaja      DATE           NOT NULL,
        observaciones  NVARCHAR(500)  NULL,
        fechaReingreso DATE           NULL,
        registradaPor  INT            NULL,
        createdAt      DATETIME2      NOT NULL
    );
    CREATE INDEX IX_EmployeeBaja_employeeId ON EmployeeBaja (employeeId);
END
"""


def ensure_table(db: Session) -> None:
    """
    DDL idempotente de EmployeeBaja.

    Se llama en el startup de la app, no en los endpoints: bajas_de_empleado
    corre en CADA request autenticado (el recorte de permisos), y meter DDL en
    ese camino seria pagar una verificacion de esquema por request.
    """
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def bajas_de_empleado(db: Session, employee_id: int) -> list[dict]:
    """
    Todas las bajas de una persona, de la mas nueva a la mas vieja.

    Devuelve el historial completo, no solo la vigente: quien decide cual
    aplica es baja_vigente, que es una regla pura y testeable aparte.
    """
    filas = db.execute(text("""
        SELECT id, employeeId, motivo, fechaBaja, observaciones,
               fechaReingreso, registradaPor, createdAt
        FROM EmployeeBaja
        WHERE employeeId = :id
        ORDER BY fechaBaja DESC
    """), {"id": employee_id}).mappings().all()
    return [dict(f) for f in filas]


def _marcar_estado(db: Session, employee_id: int, estado: str) -> None:
    """Escribe el cache cosmetico de Employee.status."""
    db.execute(text("UPDATE Employee SET status = :e, updatedAt = GETDATE() "
                    "WHERE id = :id"), {"e": estado, "id": employee_id})


ACCIONES_PENDIENTES = "('Pendiente', 'Pendiente Siguiente Aprobación')"


def _reasignar_aprobaciones(db: Session, employee_id: int, hoy: date) -> dict:
    """
    Pasa las aprobaciones que el dado de baja tenia pendientes como
    supervisor a su propio superior (Employee.managerId).

    Aprobaciones.supervisorId guarda el employeeId del supervisor, igual que
    lo escribe create_license_request. Si no tiene superior cargado, o el
    superior tambien esta de baja, no se toca nada: se cuentan para que RRHH
    sepa cuantas quedaron sin nadie que las resuelva.

    Las filas con accion='Pendiente Siguiente Aprobación' son decisiones ya
    tomadas (aprobada y derivada al siguiente supervisor) y no se reasignan.
    """
    fila = db.execute(text("SELECT managerId FROM Employee WHERE id = :id"),
                      {"id": employee_id}).mappings().first()
    jefe = fila["managerId"] if fila else None

    if (jefe is not None and jefe != employee_id
            and baja_vigente_de(db, jefe, hoy) is None):
        res = db.execute(text("""
            UPDATE Aprobaciones
            SET supervisorId = :jefe, updatedAt = GETDATE()
            WHERE supervisorId = :id
              AND accion = 'Pendiente'
        """), {"jefe": jefe, "id": employee_id})
        return {"reasignadas": res.rowcount, "sinReasignar": 0}

    pendientes = db.execute(text("""
        SELECT COUNT(*) AS n FROM Aprobaciones
        WHERE supervisorId = :id
          AND accion = 'Pendiente'
    """), {"id": employee_id}).mappings().first()
    return {"reasignadas": 0,
            "sinReasignar": int(pendientes["n"]) if pendientes else 0}


def aplicar_efectos(db: Session, employee_id: int,
                    hoy: Optional[date] = None) -> dict:
    """
    Los efectos colaterales de una baja que ya tiene efecto.

    Cancela las solicitudes de licencia sin resolver, reasigna las
    aprobaciones que tenia pendientes como supervisor y marca el cache de
    estado. No hace commit: el llamador decide la transaccion.

    Devuelve {reasignadas, sinReasignar} de sus aprobaciones como supervisor.

    Las dos sentencias de cancelacion son necesarias. License.status es lo que
    ve la persona, pero la cola del supervisor se arma leyendo Aprobaciones
    con accion pendiente: sin el segundo UPDATE la solicitud le seguiria
    apareciendo para aprobar. Se actualiza la fila que ya existe en vez de
    insertar una nueva, porque supervisorId es NOT NULL y el sistema no es un
    supervisor: la fila pendiente ya trae el suyo.
    """
    db.execute(text("""
        UPDATE License
        SET status = 'Rechazada', updatedAt = GETDATE()
        WHERE employeeId = :id
          AND status IN ('Pendiente', 'Pendiente Siguiente Aprobación')
    """), {"id": employee_id})

    db.execute(text("""
        UPDATE Aprobaciones
        SET accion = 'Rechazada',
            observacion = 'Cancelada automáticamente por la baja del empleado',
            fecha = GETDATE(), updatedAt = GETDATE()
        WHERE accion IN ('Pendiente', 'Pendiente Siguiente Aprobación')
          AND licenseId IN (SELECT id FROM License WHERE employeeId = :id)
    """), {"id": employee_id})

    aprobaciones = _reasignar_aprobaciones(db, employee_id, hoy or date.today())

    _marcar_estado(db, employee_id, ESTADO_BAJA)
    return aprobaciones


def registrar_baja(db: Session, employee_id: int, motivo: str, fecha: date,
                   observaciones: Optional[str], registrada_por: Optional[int],
                   hoy: date) -> dict:
    """
    Inserta la baja y, si ya tiene efecto, aplica sus consecuencias.

    Una fecha futura se guarda sin aplicar nada: el tick diario la aplica
    cuando llegue el dia. El recorte de accesos no depende de ese tick, porque
    se calcula con la fecha en cada request.

    Todo va en una transaccion: una baja registrada sin sus efectos dejaria
    solicitudes pendientes de alguien que ya no trabaja.
    """
    fila = db.execute(text("""
        INSERT INTO EmployeeBaja
            (employeeId, motivo, fechaBaja, observaciones, registradaPor, createdAt)
        OUTPUT INSERTED.id
        VALUES (:id, :motivo, :fecha, :obs, :por, GETDATE())
    """), {"id": employee_id, "motivo": motivo, "fecha": fecha,
           "obs": observaciones, "por": registrada_por}).fetchone()

    vigente = baja_vigente([{"fechaBaja": fecha, "fechaReingreso": None}],
                           hoy) is not None
    aprobaciones = {"reasignadas": 0, "sinReasignar": 0}
    if vigente:
        aprobaciones = aplicar_efectos(db, employee_id, hoy)

    db.commit()
    return {"id": int(fila[0]) if fila else None, "vigente": vigente,
            "aprobaciones": aprobaciones}


def borrar_baja(db: Session, employee_id: int) -> bool:
    """
    Corrige un error de carga: borra la baja abierta como si nunca existiera.

    Devuelve False si no habia ninguna abierta. Las solicitudes canceladas no
    se resucitan -ver el spec-: volver a la cola una licencia rechazada
    semanas antes confundiria mas que pedirla de nuevo.
    """
    res = db.execute(text("""
        DELETE FROM EmployeeBaja
        WHERE employeeId = :id AND fechaReingreso IS NULL
    """), {"id": employee_id})

    if res.rowcount == 0:
        return False

    _marcar_estado(db, employee_id, estado_segun_licencias(db, employee_id))
    db.commit()
    return True


def reincorporar(db: Session, employee_id: int, fecha_reingreso: date) -> bool:
    """
    Cierra la baja abierta dejandola en el historial.

    Devuelve False si no habia ninguna abierta.
    """
    res = db.execute(text("""
        UPDATE EmployeeBaja
        SET fechaReingreso = :fecha
        WHERE employeeId = :id AND fechaReingreso IS NULL
    """), {"fecha": fecha_reingreso, "id": employee_id})

    if res.rowcount == 0:
        return False

    _marcar_estado(db, employee_id, estado_segun_licencias(db, employee_id))
    db.commit()
    return True


def baja_vigente_de(db: Session, employee_id: int, hoy: date) -> Optional[dict]:
    """La baja con efecto hoy para esta persona, o None."""
    return baja_vigente(bajas_de_empleado(db, employee_id), hoy)


def bajas_bulk(db: Session, employee_ids: list[int]) -> dict[int, list[dict]]:
    """
    Todas las bajas de un lote de empleados, en UNA sola consulta.

    Es la version bulk de bajas_de_empleado, para listados: sigue el mismo
    patron "WHERE employeeId IN (...) + agrupar en Python" que ya usa
    app/routes/rrhh.py para subordinados, licencias, permisos, etc. Sin esto,
    exponer la baja en el listado costaria una consulta por empleado.
    """
    if not employee_ids:
        return {}
    ids_param = ",".join(str(i) for i in employee_ids)
    filas = db.execute(text(f"""
        SELECT employeeId, motivo, fechaBaja, fechaReingreso
        FROM EmployeeBaja
        WHERE employeeId IN ({ids_param})
    """)).mappings().all()
    agrupado: dict[int, list[dict]] = defaultdict(list)
    for f in filas:
        agrupado[f["employeeId"]].append(dict(f))
    return agrupado


def baja_para_respuesta(bajas_by_emp: dict[int, list[dict]], employee_id: int,
                        hoy: date) -> Optional[dict]:
    """
    El valor de "baja" para el payload de un empleado: {motivo, fechaBaja,
    vigente} de su baja abierta, o None si no tiene ninguna.

    Informa tambien la programada (vigente False): el perfil tiene que poder
    ofrecer cancelarla, y sin esto mostraria "Dar de baja" y dejaria apilar
    otra. vigente sale de baja_vigente, la definicion unica de "esta de baja".
    """
    bajas = bajas_by_emp.get(employee_id, [])
    b = baja_abierta(bajas)
    if b is None:
        return None
    return {"motivo": b["motivo"],
            "fechaBaja": a_date(b["fechaBaja"]).isoformat(),
            "vigente": baja_vigente([b], hoy) is not None}


def fecha_de_corte(db: Session, employee_id: int, hoy: date) -> Optional[date]:
    """
    Hasta cuando computarle a esta persona, o None si sigue trabajando.

    Es la fecha de la baja vigente, sea cual sea el motivo: quien se fue deja
    de acumular vacaciones y de generar jornadas. Lo consumen
    calcular_dias_vacaciones y rango_de_calculo.
    """
    baja = baja_vigente_de(db, employee_id, hoy)
    return a_date(baja["fechaBaja"]) if baja else None


def bajas_para_tablero(db: Session, hoy: date) -> list[dict]:
    """
    Todas las bajas registradas, con los datos del empleado para el tablero.

    Trae las tres clases -vigente, reincorporada y programada- porque las
    programadas son el unico lugar donde RRHH puede ver y corregir una baja
    cargada con preaviso antes de que llegue el dia.

    El saldo de asistencia no es una columna: es la suma de los dias. Mismo
    calculo que saldo_acumulado() en app/database/asistencia.py.
    """
    filas = db.execute(text("""
        SELECT b.id, b.employeeId, b.motivo, b.fechaBaja, b.fechaReingreso,
               b.observaciones,
               e.name, e.dni, e.email, e.photo,
               d.nombre AS departamento, o.nombre AS oficina,
               c.tipoContrato, c.fechaIngreso,
               (SELECT COALESCE(SUM(j.saldoDia), 0) FROM JornadaDiaria j
                WHERE j.employeeId = e.id) AS saldoFinal
        FROM EmployeeBaja b
        JOIN Employee e ON e.id = b.employeeId
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN (
            SELECT employeeId, MIN(fechaIngreso) AS fechaIngreso,
                   MAX(tipoContrato) AS tipoContrato
            FROM CondicionLaboral GROUP BY employeeId
        ) c ON c.employeeId = e.id
        ORDER BY b.fechaBaja DESC, e.name ASC
    """)).mappings().all()

    resultado = []
    for f in filas:
        fecha_baja = a_date(f["fechaBaja"])
        reingreso = a_date(f["fechaReingreso"])
        if reingreso is not None:
            estado = "reincorporada"
        elif fecha_baja is not None and fecha_baja > hoy:
            estado = "programada"
        else:
            estado = "vigente"

        resultado.append({
            "id": int(f["id"]),
            "employeeId": int(f["employeeId"]),
            "name": f["name"],
            "dni": f["dni"],
            "email": f["email"],
            "photo": f["photo"],
            "departamento": f["departamento"],
            "oficina": f["oficina"],
            "tipoContrato": f["tipoContrato"],
            "motivo": f["motivo"],
            "observaciones": f["observaciones"],
            "fechaIngreso": a_date(f["fechaIngreso"]).isoformat()
                            if f["fechaIngreso"] else None,
            "fechaBaja": fecha_baja.isoformat() if fecha_baja else None,
            "fechaReingreso": reingreso.isoformat() if reingreso else None,
            "antiguedadAnios": antiguedad_en_anios(f["fechaIngreso"], fecha_baja),
            "saldoFinal": float(f["saldoFinal"]) if f["saldoFinal"] is not None else 0.0,
            "estado": estado,
        })
    return resultado


def pendientes_de_aplicar(db: Session, hoy: date) -> list[int]:
    """
    Empleados con baja ya cumplida que todavia figuran activos en el cache.

    Es lo que consume el tick diario para aplicar los efectos colaterales de
    las bajas programadas. El corte de accesos no lo necesita: se calcula.
    """
    filas = db.execute(text("""
        SELECT DISTINCT b.employeeId
        FROM EmployeeBaja b
        JOIN Employee e ON e.id = b.employeeId
        WHERE b.fechaReingreso IS NULL
          AND b.fechaBaja <= :hoy
          AND (e.status IS NULL OR e.status <> :baja)
    """), {"hoy": hoy, "baja": ESTADO_BAJA}).mappings().all()
    return [int(f["employeeId"]) for f in filas]
