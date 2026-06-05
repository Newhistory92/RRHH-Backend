from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_middleware import require_any_auth
from app.database.database import SessionLocal, SessionLocalObraSocial
router = APIRouter(prefix="/stats", tags=["Statistics"], dependencies=[Depends(require_any_auth)])
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
def sync_productivity_scores(db: Session, stats_db: Session) -> None:
    scores_by_user = calculate_productivity_scores(stats_db)
    users_query = text("""
        SELECT id, employeeId
        FROM [User]
        WHERE employeeId IS NOT NULL
    """)
    users = db.execute(users_query).mappings().all()
    for user in users:
        user_id = str(user["id"]).lower()
        score = scores_by_user.get(user_id, 0.0)
        db.execute(
            text("UPDATE Employee SET productivityScore = :score WHERE id = :id"),
            {"score": score, "id": user["employeeId"]}
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
            c.tipoContrato
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
    """)
    return db.execute(emp_query).mappings().all()
@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), stats_db: Session = Depends(get_stats_db)):
    try:
        sync_productivity_scores(db, stats_db)
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
