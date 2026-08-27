from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_middleware import require_permission
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.database.score_exencion import empleados_exentos
router = APIRouter(prefix="/stats", tags=["Statistics"], dependencies=[Depends(require_permission("estadisticas.ver"))])
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
def get_stats_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()
def calculate_productivity_scores(stats_db: Session) -> dict[str, float]:
    query = text("""
        DECLARE @timeout_min INT = 10;
        DECLARE @cooldown_sec INT = 3;
        ;WITH LogsFiltrados AS (
            SELECT l.idUsuario, l.creado
            FROM [ObraSocial].[dbo].[UsuarioAccesoLogs] l
            WHERE l.creado >= DATEADD(MONTH, -12, GETDATE())
        ),
        Ordenados AS (
            SELECT *, LAG(creado) OVER (PARTITION BY idUsuario ORDER BY creado) AS prev_time
            FROM LogsFiltrados
        ),
        SinSpam AS (
            SELECT *
            FROM Ordenados
            WHERE prev_time IS NULL OR DATEDIFF(SECOND, prev_time, creado) >= @cooldown_sec
        ),
        DetectarSesiones AS (
            SELECT *,
                CASE
                    WHEN prev_time IS NULL THEN 1
                    WHEN DATEDIFF(MINUTE, prev_time, creado) > @timeout_min THEN 1
                    ELSE 0
                END AS nueva_sesion
            FROM SinSpam
        ),
        SesionesAgrupadas AS (
            SELECT *,
                SUM(nueva_sesion) OVER (
                    PARTITION BY idUsuario
                    ORDER BY creado
                    ROWS UNBOUNDED PRECEDING
                ) AS session_id
            FROM DetectarSesiones
        ),
        Sesiones AS (
            SELECT idUsuario, session_id, COUNT(*) AS eventos
            FROM SesionesAgrupadas
            GROUP BY idUsuario, session_id
        )
        SELECT
            idUsuario,
            CAST(AVG(CAST(eventos AS FLOAT)) AS DECIMAL(10,2)) AS productivityScore
        FROM Sesiones
        GROUP BY idUsuario
    """)
    rows = stats_db.execute(query).mappings().all()
    return {str(row["idUsuario"]).lower(): float(row["productivityScore"]) for row in rows}
# Cuanto puede moverse un exento respecto del promedio, por su asistencia.
# Acotado a proposito: el desempate ordena dentro del area, no compite contra
# las areas que si generan actividad medible.
MARGEN_DESEMPATE = 0.15


def aplicar_score_exentos(
    scores: dict[int, float],
    exentos: set[int],
    horas: dict[int, float],
) -> dict[int, float]:
    """
    Reemplaza el score de las areas exentas por el promedio de las demas.

    Las areas cuyo trabajo no pasa por el sistema no generan logs de acceso, asi
    que su score medido siempre da ~0 y quedan ultimas sin que eso diga nada de
    cuanto trabajan. Se les asigna el promedio de los no exentos, mas un ajuste
    derivado de su saldo de horas para que no queden todos con el mismo numero:
    una autoridad tiene que poder ver quien es el mejor DENTRO del area.

    El ajuste esta centrado en la media del propio grupo, asi que el promedio
    del grupo sigue siendo el promedio general. Quien no tiene dato de
    asistencia recibe el promedio limpio: no se lo castiga por falta de datos.

    Funcion pura, sin I/O, para poder testear la matematica sin base.
    """
    no_exentos = [s for emp_id, s in scores.items() if emp_id not in exentos and s > 0]
    if not no_exentos:
        # Sin base para promediar no se inventa nada: se deja lo que habia.
        return dict(scores)

    promedio = sum(no_exentos) / len(no_exentos)
    resultado = dict(scores)

    con_horas = {emp_id: horas[emp_id] for emp_id in exentos if emp_id in horas}

    if con_horas:
        valores = list(con_horas.values())
        media_horas = sum(valores) / len(valores)
        rango = max(valores) - min(valores)
    else:
        rango = 0.0
        media_horas = 0.0

    for emp_id in exentos:
        if emp_id not in scores:
            continue
        if emp_id in con_horas and rango > 0:
            desvio = (con_horas[emp_id] - media_horas) / rango
            resultado[emp_id] = round(promedio + desvio * MARGEN_DESEMPATE * promedio, 2)
        else:
            resultado[emp_id] = round(promedio, 2)

    return resultado


def sync_productivity_scores(db: Session, stats_db: Session) -> None:
    scores_by_user = calculate_productivity_scores(stats_db)
    users_query = text("""
        SELECT u.id, u.employeeId, e.horas
        FROM [User] u
        JOIN Employee e ON e.id = u.employeeId
        WHERE u.employeeId IS NOT NULL
    """)
    users = db.execute(users_query).mappings().all()

    scores_por_empleado: dict[int, float] = {}
    horas_por_empleado: dict[int, float] = {}

    for user in users:
        user_id = str(user["id"]).lower()
        emp_id = user["employeeId"]
        scores_por_empleado[emp_id] = scores_by_user.get(user_id, 0.0)
        if user["horas"] is not None:
            horas_por_empleado[emp_id] = float(user["horas"])

    exentos = empleados_exentos(db)
    scores_finales = aplicar_score_exentos(scores_por_empleado, exentos, horas_por_empleado)

    for emp_id, score in scores_finales.items():
        db.execute(
            text("UPDATE Employee SET productivityScore = :score WHERE id = :id"),
            {"score": score, "id": emp_id}
        )
    db.commit()
def fetch_all_employees_data(db: Session):
    emp_query = text("""
        SELECT
            e.id,
            e.name,
            e.productivityScore,
            d.nombre AS department_name,
            o.nombre AS office_name,
            c.categoria,
            c.tipoContrato,
            CASE
                WHEN ISNULL(d.scoreExento, 0) = 1 OR ISNULL(o.scoreExento, 0) = 1
                THEN 1 ELSE 0
            END AS isExento
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
    """)
    return db.execute(emp_query).mappings().all()
@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), stats_db: Session = Depends(get_stats_db)):
    try:
        try:
            sync_productivity_scores(db, stats_db)
        except Exception as sync_error:
            # La base ObraSocial es una fuente secundaria (calcula el score de
            # productividad a partir de logs de acceso). Si no está disponible,
            # el dashboard debe seguir funcionando con el último score guardado
            # en Employee.productivityScore en vez de caer entero.
            print(f"Aviso: no se pudo sincronizar productividad desde ObraSocial: {sync_error}")
        employees_raw = fetch_all_employees_data(db)
        data = [
            {
                "id": emp["id"],
                "name": emp["name"],
                "productivityScore": emp["productivityScore"],
                "department": emp["department_name"],
                "office": emp["office_name"],
                "categoria": emp["categoria"],
                "tipoContrato": emp["tipoContrato"],
                "isExento": bool(emp["isExento"]),
            }
            for emp in employees_raw
        ]
        return {"success": True, "data": data}
    except Exception as e:
        print(f"Error en dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/metadata")
def get_metadata(db: Session = Depends(get_db)):
    try:
        dept_query = text("SELECT id, nombre FROM Department ORDER BY nombre")
        departments = [dict(r) for r in db.execute(dept_query).mappings().all()]
        office_query = text("SELECT nombre, departmentId FROM Office ORDER BY nombre")
        offices = [dict(r) for r in db.execute(office_query).mappings().all()]
        dept_list = []
        for d in departments:
            dept_list.append(d["nombre"])
            for o in offices:
                if o["departmentId"] == d["id"]:
                    # Keep ASCII-only bullet to avoid encoding issues in some clients.
                    dept_list.append(f"   - {o['nombre']}")
        contratos_query = text(
            "SELECT DISTINCT tipoContrato FROM CondicionLaboral WHERE tipoContrato IS NOT NULL"
        )
        contratos = [r["tipoContrato"] for r in db.execute(contratos_query).mappings().all()]
        positions_query = text(
            "SELECT DISTINCT position FROM CondicionLaboral WHERE position IS NOT NULL"
        )
        positions = [r["position"] for r in db.execute(positions_query).mappings().all()]
        return {"success": True, "data": {"departments": dept_list, "employmentStatuses": contratos, "activityTypes": positions}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.get("/global-stats")
def get_global_stats(db: Session = Depends(get_db)):
    try:
        # 1. Productividad promedio por departamento
        dept_prod_query = text("""
            SELECT d.nombre, AVG(e.productivityScore) as avg_score, COUNT(e.id) as emp_count
            FROM Employee e
            JOIN Department d ON e.departmentId = d.id
            WHERE e.productivityScore IS NOT NULL
            GROUP BY d.nombre
            ORDER BY AVG(e.productivityScore) DESC
        """)
        dept_prod_rows = db.execute(dept_prod_query).mappings().all()
        
        best_department = {"name": "N/A", "avg": 0.0}
        department_productivity = []
        if dept_prod_rows:
            best_row = dept_prod_rows[0]
            best_department = {
                "name": best_row["nombre"],
                "avg": round(float(best_row["avg_score"] or 0), 1)
            }
            for row in dept_prod_rows:
                department_productivity.append({
                    "name": row["nombre"],
                    "productividad": round(float(row["avg_score"] or 0), 1)
                })
        # 2. Productividad promedio por actividad/posición (para baja eficiencia)
        act_prod_query = text("""
            SELECT c.position, AVG(e.productivityScore) as avg_score, COUNT(e.id) as emp_count
            FROM Employee e
            JOIN CondicionLaboral c ON c.employeeId = e.id
            WHERE e.productivityScore IS NOT NULL AND c.position IS NOT NULL
            GROUP BY c.position
        """)
        act_prod_rows = db.execute(act_prod_query).mappings().all()
        
        low_efficiency_activities = []
        for row in act_prod_rows:
            avg_score = float(row["avg_score"] or 0)
            if avg_score < 7.5:
                low_efficiency_activities.append({
                    "name": row["position"],
                    "avg": round(avg_score, 1)
                })
        # 3. Promedio de ausencias del año actual
        absences_query = text("""
            SELECT 
                CAST(COUNT(a.id) AS FLOAT) / NULLIF((SELECT COUNT(*) FROM Employee), 0) as avg_absences
            FROM Ausencia a
            WHERE YEAR(a.fecha) = YEAR(GETDATE())
        """)
        absences_row = db.execute(absences_query).mappings().first()
        avg_absences = round(float(absences_row["avg_absences"] or 0), 1) if absences_row else 0.0
        # 4. Promedio de tardanzas (promedio de los valores negativos de 'horas' en Employee)
        lateness_query = text("""
            SELECT 
                COALESCE(ABS(AVG(CAST(horas AS FLOAT))), 0.0) as avg_lateness
            FROM Employee
            WHERE horas < 0
        """)
        lateness_row = db.execute(lateness_query).mappings().first()
        avg_lateness = round(float(lateness_row["avg_lateness"] or 0), 1) if lateness_row else 0.0
        # 5. Distribución por estado
        status_query = text("""
            SELECT status, COUNT(*) AS count
            FROM Employee
            WHERE status IS NOT NULL
            GROUP BY status
        """)
        status_rows = db.execute(status_query).mappings().all()
        status_distribution = [{"name": row["status"], "value": row["count"]} for row in status_rows]
        return {
            "success": True,
            "data": {
                "bestDepartment": best_department,
                "lowEfficiencyActivities": low_efficiency_activities,
                "avgAbsences": avg_absences,
                "avgLateness": avg_lateness,
                "statusDistribution": status_distribution,
                "departmentProductivity": department_productivity
            }
        }
    except Exception as e:
        print(f"Error en global-stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
