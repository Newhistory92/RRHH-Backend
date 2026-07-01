from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from datetime import datetime, date, timedelta
from typing import Optional
from app.database.feriados import (
    ensure_table as ensure_feriado_table,
    get_feriados as get_feriados_data,
    save_feriado as save_feriado_data,
    delete_feriado as delete_feriado_data,
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)

router = APIRouter(prefix="/licenses", tags=["Licenses"])

# ---------------------------------------------------------------------------
# GET /licenses/supervisor — Obtiene el jefe directo (User ID) para aprobaciones
# ---------------------------------------------------------------------------
@router.get("/supervisor", dependencies=[Depends(require_any_auth)])
def get_employee_supervisor(employee_id: int, db: Session = Depends(get_db)):
    """
    Obtiene el supervisor directo del empleado usando la auto-relación managerId.
    Retorna { supervisor: { id: userId, name: string } } para uso del frontend.
    """
    # 1. Buscar el managerId del empleado
    query_emp = text("SELECT managerId FROM Employee WHERE id = :id")
    emp = db.execute(query_emp, {"id": employee_id}).mappings().first()
    
    if not emp or not emp["managerId"]:
        return {"supervisor": None}

    # 2. Buscar el userId y nombre del manager
    query_mgr = text("""
        SELECT u.id as userId, e.name 
        FROM [User] u
        INNER JOIN Employee e ON u.employeeId = e.id
        WHERE e.id = :mgrId
    """)
    mgr = db.execute(query_mgr, {"mgrId": emp["managerId"]}).mappings().first()
    
    if not mgr:
        return {"supervisor": None}

    return {
        "supervisor": {
            "id": mgr["userId"],
            "name": mgr["name"]
        }
    }


# ---------------------------------------------------------------------------
# GET /licenses/tipos-disponibles — Tipos de licencia permitidos para un empleado
# Triple-join: CondicionLaboral → ConfiguracionLicencias (por categoria)
# ---------------------------------------------------------------------------
@router.get("/tipos-disponibles", dependencies=[Depends(require_any_auth)])
def get_tipos_disponibles(employee_id: int, db: Session = Depends(get_db)):
    """
    Retorna los tipos de licencia que el empleado puede solicitar,
    basado en su tipoContrato (CondicionLaboral) cruzado con
    ConfiguracionLicencias.categoria. Incluye diasTotales y consumidos.
    """
    # 1. Obtener datos del empleado: tipoContrato, género, fecha de ingreso, rol
    emp_query = text("""
        SELECT cl.tipoContrato, cl.fechaIngreso, e.gender,
               r.name as roleName
        FROM Employee e
        LEFT JOIN CondicionLaboral cl ON e.id = cl.employeeId
        LEFT JOIN [User] u ON u.employeeId = e.id
        LEFT JOIN Role r ON u.roleId = r.id
        WHERE e.id = :empId
    """)
    emp_data = db.execute(emp_query, {"empId": employee_id}).mappings().first()
    
    if not emp_data:
        return {"tipos": [], "message": "No se encontró condición laboral para el empleado."}

    tipo_contrato = emp_data["tipoContrato"] or "permanente"
    tipo_config = normalizar_tipo_contrato(tipo_contrato)
    genero = emp_data["gender"] or ""
    rol = emp_data["roleName"] or ""
    fecha_ingreso = emp_data["fechaIngreso"]

    # Calcular antigüedad en años
    anios_servicio = 0
    if fecha_ingreso:
        fi = fecha_ingreso
        if isinstance(fi, str):
            try:
                fi = datetime.strptime(fi.split("T")[0], "%Y-%m-%d").date()
            except ValueError:
                fi = None
        elif hasattr(fi, "date"):
            fi = fi.date()
        if fi:
            anios_servicio = (date.today() - fi).days / 365.0

    today = date.today()
    current_cycle = today.year  # 👈 Usar año calendario actual (2026) directo

    # 2. Triple-join: ConfiguracionLicencias con ConsumoLicencias para el ciclo actual
    query = text("""
        SELECT 
            c.categoria as nombre,
            c.diasTotales,
            COALESCE(SUM(cons.diasConsumidos), 0) as consumidos
        FROM ConfiguracionLicencias c
        LEFT JOIN (
            SELECT cl_i.tipo as categoria_consumo, cl_i.diasConsumidos
            FROM ConsumoLicencias cl_i
            INNER JOIN License l_i ON cl_i.licenseId = l_i.id
            WHERE l_i.employeeId = :empId AND cl_i.anio = :anio
        ) cons ON cons.categoria_consumo = c.categoria
        WHERE c.tipo = :tipoConfig AND c.anio = :anio
        GROUP BY c.categoria, c.diasTotales
    """)
    
    rows = db.execute(query, {
        "empId": employee_id,
        "anio": current_cycle,
        "tipoConfig": tipo_config
    }).mappings().all()

    # 3. Filtros de negocio (género, antigüedad, rol)
    tipos = []
    for row in rows:
        nombre = row["nombre"]
        nombre_lower = nombre.lower()

        # Filtro por género
        if "nacimiento" in nombre_lower and genero != "Masculino":
            continue
        if "embarazo" in nombre_lower and genero != "Femenino":
            continue

        # Filtro por antigüedad: 'Sin Goce de Haberes' requiere 2+ años
        if "sin goce" in nombre_lower and anios_servicio < 2:
            continue

        # Nota: El filtro de exclusividad de licencias (RRHH o Admin) fue removido del Backend
        # de forma temporal al renderizar y trasladado al frontend con isRRHHComponent, 
        # permitiendo que la API devuelva todo el catálogo según contrato independientemente de quién sea el target.

        # Calcular días disponibles (inyectar vacaciones dinámicas si no está explícitamente configurada en la BD)
        dias_totales = row["diasTotales"]
        if "vacaciones" in nombre_lower:
            if dias_totales == 0:
                dias_vac = calcular_dias_vacaciones(tipo_contrato, fecha_ingreso)
                if dias_vac > 0:
                    dias_totales = dias_vac

        consumidos = row["consumidos"]
        disponibles = max(0, dias_totales - consumidos)

        tipos.append({
            "nombre": nombre,
            "diasTotales": dias_totales,
            "consumidos": consumidos,
            "disponibles": disponibles,
        })

    # Ordenar tipos (Vacaciones primero, luego resto alfabético)
    tipos = sorted(tipos, key=lambda x: (x["nombre"].lower() != "vacaciones", x["nombre"]))

    return {"tipos": tipos, "tipoContrato": tipo_contrato, "tipoConfig": tipo_config}


# ---------------------------------------------------------------------------
# GET /licenses/supervisores-disponibles — Lista de supervisores activos para derivar
# Fuente: tabla LicenseSupervisor + User
# ---------------------------------------------------------------------------
@router.get("/supervisores-disponibles", dependencies=[Depends(require_any_auth)])
def get_supervisores_disponibles(db: Session = Depends(get_db)):
    """
    Retorna la lista de usuarios que han actuado como supervisores en
    la tabla LicenseSupervisor (many-to-many License ↔ User).
    Se usa para el modal de derivación de aprobaciones.
    """
    query = text("""
        SELECT DISTINCT u.id, e.name, u.usuario, u.email, u.activo
        FROM LicenseSupervisor ls
        INNER JOIN [User] u ON ls.userId = u.id
        INNER JOIN Employee e ON u.employeeId = e.id
        WHERE u.activo = 1
        ORDER BY e.name
    """)
    rows = db.execute(query).mappings().all()

    supervisores = [{
        "id": r["id"],
        "name": r["name"],
        "usuario": r["usuario"],
        "email": r["email"],
    } for r in rows]

    return {"supervisores": supervisores}

# ---------------------------------------------------------------------------
# Mapeo tipoContrato BD → valor en ConfiguracionLicencias.tipo
# ---------------------------------------------------------------------------
def normalizar_tipo_contrato(tipo_contrato: str) -> str:
    tc = tipo_contrato.lower()
    if "comisionado" in tc:
        return "comisionado"
    elif "permanente" in tc or "planta" in tc:
        return "permanente"
    elif "contratado" in tc:
        return "contratado"
    elif "auditor" in tc or "medico" in tc:
        return "auditor_medico"
    return "permanente"  # fallback

# ---------------------------------------------------------------------------
# Cálculo de vacaciones según antigüedad y tipoContrato
# ---------------------------------------------------------------------------
def calcular_dias_vacaciones(tipo_contrato: str, fecha_ingreso) -> int:
    if not fecha_ingreso:
        return 0

    if isinstance(fecha_ingreso, str):
        try:
            fecha_ingreso = datetime.strptime(fecha_ingreso.split("T")[0], "%Y-%m-%d").date()
        except ValueError:
            return 0
    elif hasattr(fecha_ingreso, "date"):
        fecha_ingreso = fecha_ingreso.date()

    today  = date.today()
    meses  = (today.year - fecha_ingreso.year) * 12 + today.month - fecha_ingreso.month
    anios  = meses / 12.0
    tc     = tipo_contrato.lower()

    # Contratado: siempre 10 días excepto primer año
    if "contratado" in tc:
        if meses < 12:
            return int((meses * 10) / 12)  # proporcional, redondeo hacia abajo
        return 10

    # Planta permanente, Comisionado, Auditor médico → por antigüedad
    if meses < 6:
        return 0   # sin derecho aún
    if meses < 12:
        return int((meses * 10) / 12)   # proporcional primer año
    if anios < 5:
        return 10
    if anios < 10:
        return 15
    if anios < 15:
        return 20
    if anios < 20:
        return 25
    return 30
# ---------------------------------------------------------------------------
# GET /licenses/configuracion — Obtiene las configuraciones anuales
# ---------------------------------------------------------------------------
@router.get("/configuracion", dependencies=[Depends(require_any_auth)])
def get_configuraciones(anio: Optional[int] = None, db: Session = Depends(get_db)):
    query = "SELECT id, anio, tipo, categoria , diasTotales, createdAt, updatedAt FROM ConfiguracionLicencias"
    params = {}
    if anio:
        query += " WHERE anio = :anio"
        params["anio"] = anio
    query += " ORDER BY anio DESC, tipo ASC, categoria  ASC"
    
    config_result = db.execute(text(query), params).mappings().all()
    return {"configuraciones": [dict(c) for c in config_result]}

# ---------------------------------------------------------------------------
# POST /licenses/configuracion — Crea una nueva cuota / regla de licencia
# ---------------------------------------------------------------------------
@router.post("/configuracion", dependencies=[Depends(require_rrhh_auth)])
def create_configuracion(data: dict = Body(...), db: Session = Depends(get_db)):
    anio = data.get("anio")
    tipo = data.get("tipo")
    categoria  = data.get("categoria", "General")
    dias_totales = data.get("diasTotales")

    if not all([anio, tipo, dias_totales]):
        raise HTTPException(status_code=400, detail="Faltan datos obligatorios (anio, tipo, diasTotales)")

    try:
        result = db.execute(text("""
            INSERT INTO ConfiguracionLicencias (anio, tipo, categoria , diasTotales, createdAt, updatedAt)
            OUTPUT INSERTED.id
            VALUES (:anio, :tipo, :categoria , :diasTotales, GETDATE(), GETDATE())
        """), {
            "anio": anio,
            "tipo": tipo,
            "categoria": categoria ,
            "diasTotales": dias_totales
        })
        new_id = result.fetchone()[0]
        db.commit()
        return {"message": "Configuración creada", "id": new_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al crear. Es posible que ya exista una configuración para ese año, tipo y contrato.")

# ---------------------------------------------------------------------------
# PUT /licenses/configuracion/{id} — Actualiza una regla
# ---------------------------------------------------------------------------
@router.put("/configuracion/{config_id}", dependencies=[Depends(require_rrhh_auth)])
def update_configuracion(config_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    anio = data.get("anio")
    tipo = data.get("tipo")
    categoria = data.get("categoria")
    dias_totales = data.get("diasTotales")

    try:
        db.execute(text("""
            UPDATE ConfiguracionLicencias 
            SET anio = :anio, tipo = :tipo, categoria = :categoria, diasTotales = :dias, updatedAt = GETDATE()
            WHERE id = :id
        """), {"anio": anio, "tipo": tipo, "categoria": categoria, "dias": dias_totales, "id": config_id})
        db.commit()
        return {"message": "Configuración actualizada"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# DELETE /licenses/configuracion/{id} — Elimina una regla
# ---------------------------------------------------------------------------
@router.delete("/configuracion/{config_id}", dependencies=[Depends(require_rrhh_auth)])
def delete_configuracion(config_id: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("DELETE FROM ConfiguracionLicencias WHERE id = :id"), {"id": config_id})
        db.commit()
        return {"message": "Configuración eliminada"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /licenses/request — Crea una solicitud de licencia
# ---------------------------------------------------------------------------
@router.post("/request", dependencies=[Depends(require_any_auth)])
def create_license_request(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Crea una solicitud de licencia.
    """
    employee_id = data.get("employeeId") or data.get("solicitanteId")
    lic_type = data.get("type", "Licencias")
    start_date = data.get("startDate")
    end_date = data.get("endDate")
    message = data.get("originalMessage", "")
    status = data.get("status", "Pendiente")
    supervisor_user_id = data.get("supervisorId")
    duration = data.get("duration")

    if not employee_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Datos incompletos")

    # Bloqueo: no se puede crear una nueva solicitud si ya hay una pendiente
    # (de cualquier tipo) sin resolver.
    pendiente = db.execute(text("""
        SELECT id FROM License
        WHERE employeeId = :empId
          AND status IN ('Pendiente', 'Pendiente Siguiente Aprobación')
    """), {"empId": employee_id}).fetchone()
    if pendiente:
        raise HTTPException(
            status_code=400,
            detail="Ya tenés una solicitud de licencia pendiente de aprobación. Esperá la resolución antes de crear una nueva."
        )

    # 1. Obtener datos del solicitante (Género, Antigüedad, Rol, Contrato)
    emp_query = text("""
        SELECT e.gender, e.name AS employee_name, cl.tipoContrato, cl.fechaIngreso, r.name as roleName
        FROM Employee e
        INNER JOIN CondicionLaboral cl ON e.id = cl.employeeId
        INNER JOIN [User] u ON u.employeeId = e.id
        INNER JOIN Role r ON u.roleId = r.id
        WHERE e.id = :empId
    """)
    emp_data = db.execute(emp_query, {"empId": employee_id}).mappings().first()
    if not emp_data:
        raise HTTPException(status_code=404, detail="Datos de empleado no encontrados")

    # 2. VALIDACIONES DE NEGOCIO
    type_lower = lic_type.lower()
    
    # A. Género
    if "nacimiento" in type_lower and emp_data["gender"] != "Masculino":
        raise HTTPException(status_code=400, detail="La licencia por Nacimiento es exclusiva para empleados Varones.")
    if "embarazo" in type_lower and emp_data["gender"] != "Femenino":
        raise HTTPException(status_code=400, detail="La licencia por Embarazo es exclusiva para empleadas Mujeres.")
    
    # B. Antigüedad para 'Sin Goce de Haberes' (2 años)
    if "sin goce" in type_lower:
        fi = emp_data["fechaIngreso"]
        if fi and (date.today() - fi.date()).days < 730:
            raise HTTPException(status_code=400, detail="Requiere 2 años de antigüedad para Licencia sin Goce de Haberes.")
            
    # C. Roles RRHH para licencias médicas pesadas
    rrhh_only_types = ["lesiones de largo tratamiento", "lar", "accidente de trabajo", "enfermedad profesional", "enfermedad de miembros del grupo", "guarda o tenencia", "lic por enfermedad", "licencia sin goce de haberes", "fallecimiento en parto"]
    is_caller_rrhh = current_user.get("roleId") == ROLE_ADMIN

    if any(t in type_lower for t in rrhh_only_types) and not is_caller_rrhh:
        raise HTTPException(status_code=403, detail="Esta licencia solo puede ser tramitada por un administrador de RRHH.")

    # F. employeeId solo puede diferir del usuario autenticado si quien llama es RRHH/Admin
    # (evita que un empleado solicite licencias a nombre de otro)
    if int(employee_id) != current_user.get("employeeId") and not is_caller_rrhh:
        raise HTTPException(status_code=403, detail="No podés solicitar una licencia a nombre de otro empleado.")

    # D. Vacaciones: Ventana Oct-Abr
    if "vacaciones" in type_lower:
        try:
            sd = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            valid_months = [10, 11, 12, 1, 2, 3, 4]
            if sd.month not in valid_months:
                raise HTTPException(status_code=400, detail="Las vacaciones solo pueden tomarse entre el 1 de Octubre y el 30 de Abril.")
        except Exception: pass

    # E. Embarazo: 90 días corrido
    if "embarazo" in type_lower:
        duration = 90
        # Recalcular EndDate si es necesario
        sd = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        ed = sd + timedelta(days=90)
        end_date = ed.isoformat()

    try:
        result = db.execute(text("""
            INSERT INTO License (type, startDate, endDate, status, duracion, mensajeOriginal, employeeId, createdAt, updatedAt)
            OUTPUT INSERTED.id
            VALUES (:type, :start, :end, :status, :duration, :msg, :empId, GETDATE(), GETDATE())
        """), {
            "type": lic_type,
            "start": start_date,
            "end": end_date,
            "status": status,
            "duration": duration,
            "msg": message,
            "empId": employee_id
        })
        new_lic_id = result.fetchone()[0]

        if supervisor_user_id:
            # Retrieve the supervisor's Employee ID from their User ID
            sup_emp = db.execute(text("SELECT employeeId FROM [User] WHERE id = :uid"), {"uid": supervisor_user_id}).mappings().first()
            if sup_emp and sup_emp["employeeId"]:
                sup_emp_id = sup_emp["employeeId"]

                # Insert into Aprobaciones
                db.execute(text("""
                    INSERT INTO Aprobaciones (licenseId, supervisorId, fecha, accion, observacion, updatedAt)
                    VALUES (:licId, :supId, GETDATE(), 'Pendiente', NULL, GETDATE())
                """), {
                    "licId": new_lic_id,
                    "supId": sup_emp_id
                })

                # Insert into Message for the supervisor's inbox
                db.execute(text("""
                    INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
                    VALUES (:supId, :msg, :dur, :start, :end, 'active', GETDATE())
                """), {
                    "supId": sup_emp_id,
                    "msg": f"Nueva solicitud de licencia de {emp_data.get('employee_name', 'Empleado')}: {message}"[:250],
                    "dur": duration,
                    "start": start_date,
                    "end": end_date
                })

        db.commit()
        return {"message": "Solicitud creada exitosamente", "id": new_lic_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))



def get_tipos_para_contrato(tipo_contrato: str) -> list[str]:
    """Devuelve la lista de tipos de licencia según el contrato del empleado."""
    tc = tipo_contrato.lower()
    if "comisionado" in tc:
        return TIPOS_POR_CONTRATO["comisionado"]
    elif "permanente" in tc or "planta" in tc:
        return TIPOS_POR_CONTRATO["permanente"]
    elif "contratado" in tc:
        return TIPOS_POR_CONTRATO["contratado"]
    return TIPOS_POR_CONTRATO["permanente"]  # fallback

# ---------------------------------------------------------------------------
# SEEDER — inserta solo filas faltantes para el año dado
# Usa el tipo normalizado que ahora vive en ConfiguracionLicencias.tipo
# ---------------------------------------------------------------------------
def seed_configs_si_faltan(db: Session, anio: int):
    """
    No hardcodea días: solo se asegura de que existan filas para el año.
    Si la tabla ya tiene datos del año (insertados por el SQL anterior),
    este seed es un no-op.
    """
    existe_algo = db.execute(
        text("SELECT TOP 1 id FROM ConfiguracionLicencias WHERE anio = :anio"),
        {"anio": anio}
    ).first()

    if not existe_algo:
        # No bloqueante: solo advertimos en el log y retornamos. 
        # Esto permite que RRHH entre a la configuración y cree la fila.
        print(f"[WARN] No hay configuraciones de licencias para el año {anio}.")
        # return None

# ---------------------------------------------------------------------------
# GET /licenses/saldos
# ---------------------------------------------------------------------------
@router.get("/saldos")
def get_license_saldos(
    employee_id: int,
    db: Session = Depends(get_db)
):
    # ── 1. Condición laboral ─────────────────────────────────────────────────
    cl = db.execute(
        text("""
            SELECT tipoContrato, fechaIngreso 
            FROM CondicionLaboral 
            WHERE employeeId = :id
        """),
        {"id": employee_id}
    ).mappings().first()

    if not cl:
        return {"balances": []}

    tipo_contrato = cl["tipoContrato"].lower().strip()
    fecha_ingreso = cl["fechaIngreso"]

    today         = date.today()
    current_cycle = today.year if today.month >= 10 else today.year - 1
    min_anio      = current_cycle - 2
    expire_anio   = current_cycle - 3

    

    # ── 2. Expiración automática (VACACIONES) ────────────────────────────────
    exp_query = text("""
        SELECT
            COALESCE(SUM(c.diasTotales), 0) AS totales,
            COALESCE((
                SELECT SUM(cl2.diasConsumidos)
                FROM ConsumoLicencias cl2
                INNER JOIN License l2 ON cl2.licenseId = l2.id
                WHERE l2.employeeId = :empId
                  AND cl2.anio = :expAnio
                  AND LOWER(cl2.tipo) = 'vacaciones'
            ), 0) AS consumidos
        FROM ConfiguracionLicencias c
        WHERE LOWER(c.categoria) = 'vacaciones'
          AND LOWER(c.tipo) = :tipoContrato
          AND c.anio = :expAnio
    """)

    exp = db.execute(exp_query, {
        "empId": employee_id,
        "expAnio": expire_anio,
        "tipoContrato": tipo_contrato
    }).mappings().first()

    if exp and (exp["totales"] - exp["consumidos"]) > 0:
        remanente = exp["totales"] - exp["consumidos"]
        try:
            lic_id = db.execute(text("""
                INSERT INTO License (
                    type, startDate, endDate, status, duracion,
                    mensajeOriginal, employeeId, createdAt, updatedAt
                )
                OUTPUT INSERTED.id
                VALUES (
                    'Expiración Vacaciones', GETDATE(), GETDATE(),
                    'Auditada', :dias,
                    'Expiración automática por ciclo de 3 años',
                    :empId, GETDATE(), GETDATE()
                )
            """), {"dias": remanente, "empId": employee_id}).fetchone()

            if lic_id:
                db.execute(text("""
                    INSERT INTO ConsumoLicencias (
                        anio, tipo, diasConsumidos, licenseId,
                        fechaConsumo, createdAt, updatedAt
                    )
                    VALUES (:anio, 'Vacaciones', :dias, :licId, GETDATE(), GETDATE(), GETDATE())
                """), {
                    "anio": expire_anio,
                    "dias": remanente,
                    "licId": lic_id[0]
                })

                db.commit()

        except Exception as e:
            db.rollback()
            print(f"[WARN] Expiración silenciosa: {e}")

    # ── 3. Obtener balances ──────────────────────────────────────────────────
    rows_query = text("""
        SELECT
            c.anio,
            c.categoria AS tipoLicencia,
            c.tipo AS contrato,
            c.diasTotales,
            COALESCE(SUM(cons.diasConsumidos), 0) AS diasConsumidos
        FROM ConfiguracionLicencias c
        LEFT JOIN (
            SELECT cl_i.anio, cl_i.tipo, cl_i.diasConsumidos
            FROM ConsumoLicencias cl_i
            INNER JOIN License l_i ON cl_i.licenseId = l_i.id
            WHERE l_i.employeeId = :empId
        ) cons 
            ON cons.anio = c.anio 
           AND LOWER(cons.tipo) = LOWER(c.categoria)
        WHERE LOWER(c.tipo) = :tipoContrato
          AND c.anio >= :minAnio
        GROUP BY c.anio, c.categoria, c.tipo, c.diasTotales
        ORDER BY c.anio DESC, c.categoria
    """)

    rows = db.execute(rows_query, {
        "empId": employee_id,
        "tipoContrato": tipo_contrato,
        "minAnio": min_anio
    }).mappings().all()


     # ── 🔥 4. Obtener datos para restricciones ───────────────────────────────
    emp_query = text("""
        SELECT e.gender, r.name as roleName
        FROM Employee e
        INNER JOIN [User] u ON u.employeeId = e.id
        INNER JOIN Role r ON u.roleId = r.id
        WHERE e.id = :empId
    """)

    emp_data = db.execute(emp_query, {"empId": employee_id}).mappings().first()

    gender = emp_data["gender"] if emp_data else None
    role_name = (emp_data["roleName"] or "").lower() if emp_data else ""

    rrhh_only_types = [
        "lesiones de largo tratamiento",
        "lar",
        "accidente de trabajo",
        "enfermedad profesional",
        "enfermedad de miembros del grupo",
        "guarda o tenencia",
        "lic por enfermedad",
        "licencia sin goce de haberes",
        "fallecimiento en parto"
    ]
    # ── 5. Armar respuesta ───────────────────────────────────────────────────
    dias_vac = calcular_dias_vacaciones(tipo_contrato, fecha_ingreso)

    balances = []

    for row in rows:
        tipo_lower = row["tipoLicencia"].lower()

        # ── FILTRO POR GÉNERO ─────────────────────
        if "nacimiento" in tipo_lower and gender != "Masculino":
            continue

        if "embarazo" in tipo_lower and gender != "Femenino":
            continue

        # ── FILTRO POR ROL ────────────────────────
        if any(t in tipo_lower for t in rrhh_only_types):
            if role_name not in ["RRHH", "ADMIN"]:
                continue

        # ── LÓGICA EXISTENTE ─────────────────────
        es_vac = tipo_lower == "vacaciones"

        totales = dias_vac if es_vac else row["diasTotales"]

        consumidos  = row["diasConsumidos"]
        disponibles = max(0, totales - consumidos)

        balances.append({
            "anio": row["anio"],
            "tipo": row["tipoLicencia"],
            "contrato": row["contrato"],
            "diasTotales": totales,
            "consumidos": consumidos,
            "disponibles": disponibles,
        })

    return {"balances": balances}
# ---------------------------------------------------------------------------
# GET /licenses/requests (Historial)
# ---------------------------------------------------------------------------
@router.get("/requests", dependencies=[Depends(require_any_auth)])
def get_license_requests(status: Optional[str] = None, employee_id: Optional[int] = None, supervisor_emp_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = """
        SELECT l.id, l.type, l.startDate, l.endDate, l.status, l.duracion as duration, 
               l.mensajeOriginal, l.createdAt, l.updatedAt, l.employeeId as solicitanteId,
               e.name as solicitanteName,
               e.managerId as managerId,
               m.name as managerName
        FROM License l
        LEFT JOIN Employee e ON e.id = l.employeeId
        LEFT JOIN Employee m ON e.managerId = m.id
        WHERE 1=1
    """
    params = {}
    if status:
        query += " AND l.status = :status"; params["status"] = status
    if employee_id:
        query += " AND l.employeeId = :empId"; params["empId"] = employee_id
    if supervisor_emp_id:
        query += " AND l.id IN (SELECT licenseId FROM Aprobaciones WHERE supervisorId = :supId AND (accion = 'Pendiente' OR accion = 'Pendiente Siguiente Aprobación'))"; params["supId"] = supervisor_emp_id

    query += " ORDER BY l.createdAt DESC"
    results = db.execute(text(query), params).mappings().all()
    
    # Formatear devolviendo solicitanteName y opcionalmente manager (jefe del solicitante)
    requests = []
    for r in results:
        req = dict(r)
        req["observacion"] = r["mensajeOriginal"]
        req["manager"] = {
            "id": r["managerId"],
            "name": r["managerName"]
        } if r["managerId"] else None
        requests.append(req)

    return {"requests": requests}

# ---------------------------------------------------------------------------
# Helper: Sincronizar Employee.status según licencias activas
# ---------------------------------------------------------------------------
def _sync_employee_status(db: Session, employee_id: int):
    """
    Compara la fecha actual con las licencias aprobadas del empleado.
    - Si hoy está dentro del rango [startDate, endDate] de alguna licencia aprobada → status = 'Licencia'
    - Si no hay ninguna licencia activa hoy → status = 'Activo'
    """
    print(f"console.log: Sincronizando status del Employee {employee_id}...")
    active_lic = db.execute(text("""
        SELECT id FROM License
        WHERE employeeId = :empId
          AND status = 'Aprobada'
          AND CAST(startDate AS DATE) <= CAST(GETDATE() AS DATE)
          AND CAST(endDate AS DATE) >= CAST(GETDATE() AS DATE)
    """), {"empId": employee_id}).first()

    new_status = "Licencia" if active_lic else "Activo"
    print(f"console.log: Employee Status Updated to: {new_status}")
    db.execute(text("""
        UPDATE Employee SET status = :status, updatedAt = GETDATE() WHERE id = :empId
    """), {"status": new_status, "empId": employee_id})


# ---------------------------------------------------------------------------
# PATCH /licenses/requests/{id}/status — Aprobación/Rechazo transaccional
# ---------------------------------------------------------------------------
@router.patch("/requests/{license_id}/status", dependencies=[Depends(require_any_auth)])
def update_license_status(license_id: int, data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    status = data.get("status")
    observacion = data.get("observacion", "")
    supervisor_emp_id = data.get("supervisorId")

    # Quien aprueba/rechaza debe ser el supervisor indicado (su propio employeeId)
    # o un usuario RRHH/Admin -- evita que cualquier empleado autenticado apruebe
    # o rechace licencias ajenas llamando al endpoint directamente.
    if supervisor_emp_id and supervisor_emp_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenés permiso para gestionar esta solicitud de licencia.")

    print(f"console.log: Transaction Started for License: {license_id}, status={status}, supervisor={supervisor_emp_id}")

    lic = db.execute(text("SELECT * FROM License WHERE id = :id"), {"id": license_id}).mappings().first()
    if not lic:
        raise HTTPException(status_code=404, detail="Licencia no encontrada")

    try:
        # ── Paso A: Actualizar License.status ──
        db.execute(text("UPDATE License SET status = :status, updatedAt = GETDATE() WHERE id = :id"), {"status": status, "id": license_id})
        print(f"console.log: License {license_id} status → {status}")

        if supervisor_emp_id:
            # ── Paso B: Actualizar Aprobaciones (UPDATE, no INSERT duplicado) ──
            res = db.execute(text("""
                UPDATE Aprobaciones 
                SET accion = :status, observacion = :obs, fecha = GETDATE(), updatedAt = GETDATE() 
                WHERE licenseId = :licId 
                  AND supervisorId = :supId 
                  AND (accion = 'Pendiente' OR accion = 'Pendiente Siguiente Aprobación')
            """), {"licId": license_id, "supId": supervisor_emp_id, "status": status, "obs": observacion})
            
            # Fallback: si no existía el registro pendiente, insertar
            if res.rowcount == 0:
                db.execute(text("""
                    INSERT INTO Aprobaciones (licenseId, supervisorId, fecha, accion, observacion, updatedAt)
                    VALUES (:licId, :supId, GETDATE(), :status, :obs, GETDATE())
                """), {"licId": license_id, "supId": supervisor_emp_id, "status": status, "obs": observacion})
            print(f"console.log: Aprobaciones actualizada para supervisor {supervisor_emp_id}")

            # ── Paso C: Derivación al siguiente supervisor (si corresponde) ──
            siguiente_supervisor_id = data.get("siguienteSupervisorId")
            if siguiente_supervisor_id:
                db.execute(text("""
                    INSERT INTO Aprobaciones (licenseId, supervisorId, fecha, accion, observacion, updatedAt)
                    VALUES (:licId, :sigSupId, GETDATE(), 'Pendiente', NULL, GETDATE())
                """), {"licId": license_id, "sigSupId": siguiente_supervisor_id})
                print(f"console.log: Derivada a siguiente supervisor {siguiente_supervisor_id}")

            # ── Paso D: Notificación al solicitante + Limpieza del Message del supervisor ──
            if status in ["Aprobada", "Rechazada"]:
                sup_name_row = db.execute(text("SELECT name FROM Employee WHERE id = :supId"), {"supId": supervisor_emp_id}).mappings().first()
                sup_name = sup_name_row["name"] if sup_name_row else "Supervisor"
                
                start_str = lic['startDate'][:10] if isinstance(lic['startDate'], str) else lic['startDate'].strftime('%Y-%m-%d')
                msg_text = f"Su solicitud de {lic['type']} para la fecha {start_str} ha sido {status} por {sup_name}"

                # Insertar notificación para el EMPLEADO solicitante
                db.execute(text("""
                    INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
                    VALUES (:empId, :msg, :dur, :start, :end, 'active', GETDATE())
                """), {
                    "empId": lic["employeeId"],
                    "msg": msg_text,
                    "dur": lic["duracion"],
                    "start": lic["startDate"],
                    "end": lic["endDate"]
                })
                print(f"console.log: Notificación enviada al empleado {lic['employeeId']}")

                # Archivar el Message que notificó al supervisor (cambiar status a 'archived')
                db.execute(text("""
                    UPDATE Message SET status = 'archived'
                    WHERE employeeId = :supId 
                      AND startDate = :start AND endDate = :end
                      AND status = 'active'
                """), {
                    "supId": supervisor_emp_id,
                    "start": lic["startDate"],
                    "end": lic["endDate"]
                })
                print(f"console.log: Message del supervisor {supervisor_emp_id} archivado")

        # ── Paso E: Si se aprueba, registrar consumo (solo si no estaba ya Aprobada,
        # para que una segunda llamada al mismo license_id -- doble click, reintento de
        # red -- no duplique el ConsumoLicencias) ──
        if status == "Aprobada" and lic['duracion'] and lic['status'] != "Aprobada":
            if isinstance(lic['startDate'], str):
                anio_consumo = int(lic['startDate'][:4])
            else:
                anio_consumo = lic['startDate'].year
                
            db.execute(text("""
                INSERT INTO ConsumoLicencias (anio, tipo, diasConsumidos, licenseId, fechaConsumo, createdAt, updatedAt)
                VALUES (:anio, :tipo, :dias, :licId, GETDATE(), GETDATE(), GETDATE())
            """), {"anio": anio_consumo, "tipo": lic['type'], "dias": lic['duracion'], "licId": license_id})
            print(f"console.log: ConsumoLicencias insertado → {lic['duracion']} días de {lic['type']}")

            # ── Paso F: Sincronizar Employee.status inmediatamente ──
            _sync_employee_status(db, lic["employeeId"])

        db.commit()
        print(f"console.log: ✅ Transacción completada exitosamente para License {license_id}")
        return {"message": f"Estado: {status}", "licenseId": license_id}
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /licenses/aplicar — Endpoint exclusivo para RRHH: aplicar licencia
# desde la bandeja de mensajes del dashboard de RRHH
# ---------------------------------------------------------------------------
@router.post("/aplicar", dependencies=[Depends(require_rrhh_auth)])
def rrhh_apply_license(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Transacción completa para que RRHH aplique una licencia desde su dashboard.
    Recibe: { employeeId, messageId, type, startDate, endDate, days }
    NOTA: El employeeId del frontend puede ser el del SUPERVISOR (porque el mensaje
    fue enviado al supervisor). Por eso primero buscamos la License real por fechas.
    """
    frontend_emp_id = data.get("employeeId")
    message_id = data.get("messageId")
    lic_type = data.get("type", "Vacaciones")
    start_date = data.get("startDate")
    end_date = data.get("endDate")
    days = data.get("days")
    observacion = data.get("observacion", "Aplicada por RRHH")

    print(f"console.log: RRHH aplicando licencia. frontend_emp_id={frontend_emp_id}, Message={message_id}")

    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Datos incompletos: startDate y endDate son requeridos")

    try:
        # ── Paso 1: Buscar la License REAL por fechas (sin filtrar por employeeId) ──
        # La licencia fue creada para el empleado solicitante, NO para el supervisor.
        existing_lic = db.execute(text("""
            SELECT TOP 1 id, employeeId FROM License
            WHERE startDate = :start AND endDate = :end
            ORDER BY createdAt DESC
        """), {"start": start_date, "end": end_date}).mappings().first()

        if existing_lic:
            license_id = existing_lic["id"]
            # Usar el employeeId REAL de la licencia, no el del frontend
            real_employee_id = existing_lic["employeeId"]
            db.execute(text("""
                UPDATE License SET status = 'Aprobada', updatedAt = GETDATE() WHERE id = :id
            """), {"id": license_id})
            print(f"console.log: License existente {license_id} (Employee real: {real_employee_id}) → Aprobada")
        else:
            # Si no existe licencia previa, usar el employeeId del frontend como fallback
            real_employee_id = frontend_emp_id
            if not real_employee_id:
                raise HTTPException(status_code=400, detail="No se encontró licencia existente y falta employeeId")
            result = db.execute(text("""
                INSERT INTO License (type, startDate, endDate, status, duracion, mensajeOriginal, employeeId, createdAt, updatedAt)
                OUTPUT INSERTED.id
                VALUES (:type, :start, :end, 'Aprobada', :days, :obs, :empId, GETDATE(), GETDATE())
            """), {
                "type": lic_type, "start": start_date, "end": end_date,
                "days": days, "obs": observacion, "empId": real_employee_id
            })
            license_id = result.fetchone()[0]
            print(f"console.log: Nueva License {license_id} creada para Employee {real_employee_id}")

        # ── Paso 2: Registrar consumo de días ──
        if days:
            if isinstance(start_date, str):
                anio = int(start_date[:4])
            else:
                anio = start_date.year

            db.execute(text("""
                INSERT INTO ConsumoLicencias (anio, tipo, diasConsumidos, licenseId, fechaConsumo, createdAt, updatedAt)
                VALUES (:anio, :tipo, :dias, :licId, GETDATE(), GETDATE(), GETDATE())
            """), {"anio": anio, "tipo": lic_type, "dias": days, "licId": license_id})
            print(f"console.log: ConsumoLicencias → {days} días de {lic_type}")

        # ── Paso 3: Archivar el mensaje procesado ──
        if message_id:
            db.execute(text("""
                UPDATE Message SET status = 'archived' WHERE id = :msgId
            """), {"msgId": message_id})
            print(f"console.log: Message {message_id} archivado")

        # ── Paso 4: Sincronizar Employee.status del EMPLEADO REAL (no del supervisor) ──
        _sync_employee_status(db, real_employee_id)

        db.commit()
        print(f"console.log: ✅ RRHH aplicó licencia. License={license_id}, Employee REAL={real_employee_id}")
        return {
            "message": "Licencia aplicada correctamente por RRHH",
            "licenseId": license_id,
            "employeeId": real_employee_id
        }
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Feriados de empresa (configurables por RRHH)
# ---------------------------------------------------------------------------
@router.get("/feriados", dependencies=[Depends(require_any_auth)])
def list_feriados(db: Session = Depends(get_db)):
    """Lista los feriados de empresa activos."""
    ensure_feriado_table(db)
    try:
        return {"feriados": get_feriados_data(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener feriados: {str(e)}")


@router.post("/feriados", dependencies=[Depends(require_rrhh_auth)])
def create_feriado(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea un feriado de empresa."""
    ensure_feriado_table(db)
    fecha = data.get("fecha")
    nombre = data.get("nombre")

    if not fecha or not nombre:
        raise HTTPException(status_code=400, detail="fecha y nombre son requeridos")

    try:
        new_id = save_feriado_data(db, fecha, nombre)
        return {"success": True, "id": new_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar feriado: {str(e)}")


@router.delete("/feriados/{feriado_id}", dependencies=[Depends(require_rrhh_auth)])
def delete_feriado_endpoint(feriado_id: int, db: Session = Depends(get_db)):
    """Soft delete de un feriado de empresa."""
    ensure_feriado_table(db)
    try:
        deleted = delete_feriado_data(db, feriado_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Feriado no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar feriado: {str(e)}")

