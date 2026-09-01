from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_middleware import require_permission
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.database.score_exencion import empleados_exentos
from app.database.score_historico import (
    FORMULA_ACTUAL,
    ensure_table as ensure_historico,
    historial_empleado,
    registrar_corrida,
)
from app.database.asistencia_merito import cumplimiento_por_empleado
from app.database.feedback_config import get_periodo_actual
from app.services.feedback_score import puntaje_feedback
from app.services.merito import armar_ficha
from app.services.turnero_client import obtener_metricas

# Ventana del calculo, en meses. Vive aca porque queda registrada en cada
# corrida del historial: un score viejo se lee contra la ventana con la que
# se lo calculo, no contra la de hoy.
VENTANA_MESES = 12
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
def calculate_productivity_scores(stats_db: Session) -> dict[str, dict]:
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
            CAST(AVG(CAST(eventos AS FLOAT)) AS DECIMAL(10,2)) AS productivityScore,
            COUNT(*) AS sesiones,
            SUM(eventos) AS eventos
        FROM Sesiones
        GROUP BY idUsuario
    """)
    rows = stats_db.execute(query).mappings().all()
    # Se devuelven tambien sesiones y eventos, no solo el promedio: son los
    # insumos que quedan guardados en ScoreHistorico para poder explicar de
    # donde salio el numero de una persona en una fecha.
    return {
        str(row["idUsuario"]).lower(): {
            "score": float(row["productivityScore"]),
            "sesiones": int(row["sesiones"]),
            "eventos": int(row["eventos"]),
        }
        for row in rows
    }
# Cuanto puede moverse un exento respecto del promedio, por su asistencia.
# Acotado a proposito: el desempate ordena dentro del area, no compite contra
# las areas que si generan actividad medible.
MARGEN_DESEMPATE = 0.15


def aplicar_score_exentos(
    scores: dict[int, float | None],
    exentos: set[int],
    horas: dict[int, float],
) -> dict[int, float | None]:
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
    # None es "nunca se lo midio", no un cero: no entra al promedio. Si contara
    # como 0 bajaria el numero que se les reparte a los exentos por un dato que
    # nadie tiene.
    no_exentos = [
        s for emp_id, s in scores.items()
        if emp_id not in exentos and s is not None and s > 0
    ]
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


def asignar_scores(
    empleados: list[int],
    idusuario_por_empleado: dict[int, str],
    scores_by_user: dict[str, float],
) -> dict[int, float | None]:
    """
    Le asigna a cada empleado su score medido, o None si no se lo pudo medir.

    Hay dos formas de quedarse sin dato y ninguna significa cero: que no se
    haya resuelto su identidad en ObraSocial, o que la haya resuelto pero no
    tenga actividad en la ventana. En los dos casos el trabajo de la persona
    no paso por ese sistema, que no es lo mismo que no haber trabajado.

    Todo empleado aparece en el resultado. Si se omitiera a los no medidos, el
    UPDATE no los tocaria y les quedaria el score de una corrida anterior.

    Funcion pura, sin I/O.
    """
    resultado: dict[int, float | None] = {}
    for emp_id in empleados:
        id_usuario = idusuario_por_empleado.get(emp_id)
        resultado[emp_id] = scores_by_user.get(id_usuario) if id_usuario else None
    return resultado


def score_por_hora(eventos: int | None, horas: float | None) -> float | None:
    """
    Eventos registrados por hora efectivamente trabajada.

    Reemplaza al promedio de eventos por sesion, que premiaba entrar poco y
    quedarse: concentrar la misma actividad en menos sesiones subia el numero
    sin trabajar mas. Las horas salen del reloj fisico, asi que el denominador
    no se puede inflar desde el sistema donde se generan los eventos.

    Sin horas no hay score: dividir por cero o asumir una jornada seria
    inventar el numero. Con horas y sin eventos si hay un cero real -la
    persona trabajo y no genero actividad en este sistema-, que es distinto de
    no haber sido medida.

    Funcion pura, sin I/O.
    """
    if horas is None or horas <= 0:
        return None
    if eventos is None:
        return None
    return round(eventos / horas, 2)


def vincular_por_dni(db: Session) -> dict[int, str]:
    """
    employeeId -> idUsuario de ObraSocial, enlazados por numero de documento.

    Antes se comparaba User.id contra idUsuario directamente. User.id tiene
    formato mixto -enteros como '10' conviviendo con GUIDs- mientras idUsuario
    es siempre GUID, asi que el join fallaba para casi todos y el empleado
    quedaba sin score sin que nada lo avisara.

    El DNI es un identificador del mundo real, estable y verificable, y es la
    misma via por la que ya se vincula el Turnero. Se excluyen los usuarios
    anulados para no puntuar sobre una cuenta dada de baja.
    """
    filas = db.execute(text("""
        SELECT e.id AS employeeId, u.idUsuario
        FROM Employee e
        INNER JOIN [ObraSocial].[dbo].[Persona] p
            ON LTRIM(RTRIM(p.numeroDocPersona)) = LTRIM(RTRIM(e.dni))
        INNER JOIN [ObraSocial].[dbo].[Usuario] u
            ON u.idPersona = p.idPersona
        WHERE e.dni IS NOT NULL
          AND LTRIM(RTRIM(e.dni)) <> ''
          AND ISNULL(u.anulado, 0) = 0
    """)).mappings().all()
    return {int(f["employeeId"]): str(f["idUsuario"]).lower() for f in filas}


def vincular_por_user_id(db: Session) -> dict[int, str]:
    """
    employeeId -> idUsuario, para los empleados cuyo User.id ES el GUID.

    Parte de las cuentas de RRHH se crearon con el mismo identificador que la
    cuenta de ObraSocial, asi que ahi el User.id sirve de vinculo legitimo: un
    GUID no coincide por casualidad. Los User.id con formato entero no matchean
    contra ningun GUID, asi que no generan falsos positivos.

    Existe porque el DNI solo no alcanza: hay empleados sin Persona cargada en
    ObraSocial que igual tienen actividad bajo su GUID.
    """
    filas = db.execute(text("""
        SELECT u.employeeId, u.id AS idUsuario
        FROM [User] u
        WHERE u.employeeId IS NOT NULL
    """)).mappings().all()
    return {int(f["employeeId"]): str(f["idUsuario"]).lower() for f in filas}


def horas_trabajadas_por_empleado(db: Session, meses: int = VENTANA_MESES) -> dict[int, float]:
    """
    Horas efectivamente trabajadas por empleado en la ventana, desde el reloj.

    Es el denominador del score. Solo suma jornadas con horas cargadas: un dia
    sin marcaciones no aporta ni al numerador ni al denominador, asi que no
    diluye el resultado de quien falto con licencia.
    """
    filas = db.execute(text("""
        SELECT employeeId, SUM(horasTrabajadas) AS horas
        FROM JornadaDiaria
        WHERE fecha >= DATEADD(MONTH, -:meses, GETDATE())
          AND horasTrabajadas IS NOT NULL
        GROUP BY employeeId
    """), {"meses": meses}).mappings().all()
    return {int(f["employeeId"]): float(f["horas"]) for f in filas if f["horas"]}


def combinar_identidades(
    por_dni: dict[int, str],
    por_user_id: dict[int, str],
) -> dict[int, str]:
    """
    Une las dos vias de vinculacion, con el DNI mandando.

    El DNI es un identificador del mundo real y verificable; el User.id
    coincide por como se creo la cuenta. Ante discrepancia gana el DNI, y el
    User.id queda para cubrir a quien el DNI no resuelve.

    Funcion pura, sin I/O.
    """
    return {**por_user_id, **por_dni}


def metodos_vinculo(
    por_dni: dict[int, str],
    por_user_id: dict[int, str],
) -> dict[int, str]:
    """
    Con que via se resolvio la identidad de cada empleado.

    Espeja la precedencia de combinar_identidades -el DNI manda- para que el
    historial no mienta sobre el origen del numero que guarda.

    Funcion pura, sin I/O.
    """
    metodos = {emp_id: "user_id" for emp_id in por_user_id}
    metodos.update({emp_id: "dni" for emp_id in por_dni})
    return metodos


def serie_historica(db: Session, employee_id: int, limite: int = 6) -> list[float | None]:
    """
    Ultimos scores de una persona, del mas viejo al mas nuevo.

    La consulta ordena descendente para poder usar TOP, y el resultado se
    invierte: describir_trayectoria compara el primer valor contra el ultimo y
    necesita orden cronologico.

    Los None se conservan: son corridas en las que hubo calculo y no se pudo
    medir, que es distinto de no haber corrido.
    """
    filas = db.execute(text("""
        SELECT TOP (:limite) score
        FROM ScoreHistorico
        WHERE employeeId = :emp
        ORDER BY calculadoEn DESC
    """), {"emp": employee_id, "limite": limite}).mappings().all()
    return [float(f["score"]) if f["score"] is not None else None for f in reversed(filas)]


def sync_productivity_scores(db: Session, stats_db: Session) -> None:
    """
    Recalcula el score de todos los empleados y deja constancia de la corrida.

    Ya no corre al abrir el panel sino desde el scheduler: recalcular en cada
    apertura pisaba los valores sin dejar rastro de que numero tuvo cada
    persona ni de que lo produjo.
    """
    ensure_historico(db)

    detalle_por_usuario = calculate_productivity_scores(stats_db)
    scores_by_user = {uid: d["score"] for uid, d in detalle_por_usuario.items()}

    empleados_raw = db.execute(text("SELECT id, horas FROM Employee")).mappings().all()
    empleados = [int(e["id"]) for e in empleados_raw]
    horas_por_empleado: dict[int, float] = {
        int(e["id"]): float(e["horas"]) for e in empleados_raw if e["horas"] is not None
    }

    por_dni = vincular_por_dni(db)
    por_user_id = vincular_por_user_id(db)
    identidades = combinar_identidades(por_dni, por_user_id)
    metodos = metodos_vinculo(por_dni, por_user_id)

    # El score medido ya no es el promedio de eventos por sesion que venia de
    # ObraSocial, sino los eventos totales sobre las horas del reloj. Por eso
    # se toma el conteo de eventos y se divide aca, en vez de usar el promedio
    # que calcula la consulta.
    horas = horas_trabajadas_por_empleado(db)
    eventos_por_empleado = {
        emp_id: (detalle_por_usuario.get(identidades.get(emp_id) or "") or {}).get("eventos")
        for emp_id in empleados
    }
    scores_por_empleado: dict[int, float | None] = {
        emp_id: score_por_hora(eventos_por_empleado.get(emp_id), horas.get(emp_id))
        for emp_id in empleados
    }

    exentos = empleados_exentos(db)
    scores_finales = aplicar_score_exentos(scores_por_empleado, exentos, horas_por_empleado)

    for emp_id, score in scores_finales.items():
        db.execute(
            text("UPDATE Employee SET productivityScore = :score WHERE id = :id"),
            {"score": score, "id": emp_id}
        )
    db.commit()

    # Se registran todos, incluidos los que quedaron sin medir: saber que
    # alguien no era medible en una fecha es parte del historial, y es lo que
    # evita que su ausencia se lea despues como bajo desempeno.
    registrar_corrida(db, [
        {
            "employeeId": emp_id,
            "score": scores_finales.get(emp_id),
            "metodoVinculo": metodos.get(emp_id),
            "idUsuario": identidades.get(emp_id),
            "sesiones": (detalle_por_usuario.get(identidades.get(emp_id) or "") or {}).get("sesiones"),
            "eventos": (detalle_por_usuario.get(identidades.get(emp_id) or "") or {}).get("eventos"),
            "esExento": emp_id in exentos,
            "ventanaMeses": VENTANA_MESES,
            "formula": FORMULA_ACTUAL,
        }
        for emp_id in empleados
    ])
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
def get_dashboard(db: Session = Depends(get_db)):
    try:
        # El score ya no se recalcula al abrir el panel: se lee el ultimo
        # valor persistido. Recalcular aca pisaba los numeros de todos en cada
        # apertura, sin dejar registro de que tuvo cada persona ni de cuando,
        # asi que una decision tomada sobre el ranking no se podia reconstruir.
        # La corrida vive ahora en el scheduler (job "score_productividad") y
        # se puede disparar a mano con POST /stats/recalcular.
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


@router.post("/recalcular", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def recalcular_scores(db: Session = Depends(get_db), stats_db: Session = Depends(get_stats_db)):
    """
    Dispara una corrida del score a pedido.

    El calculo dejo de correr al abrir el panel, asi que sin esto RRHH tendria
    que esperar al job diario para ver el efecto de un cambio -marcar un area
    como exenta, corregir un DNI-. Queda registrada en el historial como
    cualquier otra corrida.
    """
    try:
        sync_productivity_scores(db, stats_db)
    except Exception as e:
        # ObraSocial es una fuente secundaria: que no responda no debe dejar al
        # panel sin datos, sigue estando el ultimo valor persistido.
        raise HTTPException(status_code=502, detail=f"No se pudo recalcular: {e}")
    return {"success": True, "mensaje": "Scores recalculados y registrados en el historial."}


@router.get("/historial/{employee_id}", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def get_historial_score(employee_id: int, db: Session = Depends(get_db)):
    """
    Corridas registradas para un empleado, de la mas reciente a la mas vieja.

    Responde "por que esta persona tuvo este numero en esta fecha": con que
    identidad se la vinculo, por que via, cuantas sesiones y eventos lo
    produjeron y con que ventana.
    """
    ensure_historico(db)
    return {"success": True, "data": historial_empleado(db, employee_id)}


@router.get("/merito/{department_id}", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def get_merito_gerencia(department_id: int, db: Session = Depends(get_db)):
    """
    Ficha comparativa de las personas de una gerencia, para decidir un ascenso.

    El universo es la gerencia y no toda la nomina a proposito: comparar un
    administrativo con alguien de ventanilla no dice nada, y era el defecto que
    tenia el ranking global.

    No devuelve un puntaje compuesto. Cada dimension viaja por separado con su
    detalle y con si esta medida, mas la cobertura, para que quien decide vea
    tambien cuanta evidencia tiene detras de cada persona.
    """
    from app.routes.feedback import cargar_respuestas_normalizadas

    ensure_historico(db)

    empleados = db.execute(text("""
        SELECT e.id, e.name, e.dni, c.position
        FROM Employee e
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.departmentId = :dep
        ORDER BY e.name
    """), {"dep": department_id}).mappings().all()

    if not empleados:
        return {"success": True, "data": {"departmentId": department_id, "fichas": []}}

    cumplimientos = cumplimiento_por_empleado(db, VENTANA_MESES)
    hasta = date.today()
    desde = hasta - timedelta(days=30 * VENTANA_MESES)
    metricas = obtener_metricas(desde, hasta)

    periodo = get_periodo_actual(db)
    respuestas = cargar_respuestas_normalizadas(db, periodo)

    scores = {
        int(r["id"]): (float(r["productivityScore"]) if r["productivityScore"] is not None else None)
        for r in db.execute(text(
            "SELECT id, productivityScore FROM Employee WHERE departmentId = :dep"
        ), {"dep": department_id}).mappings().all()
    }

    fichas = []
    for emp in empleados:
        emp_id = int(emp["id"])
        dni = (emp["dni"] or "").strip()
        ficha = armar_ficha(
            employee_id=emp_id,
            nombre=emp["name"],
            position=emp["position"],
            cumplimiento=cumplimientos.get(emp_id),
            actividad=scores.get(emp_id),
            turnero=metricas.get(dni),
            feedback=puntaje_feedback(respuestas.get(emp_id, [])),
            historial=serie_historica(db, emp_id),
        )
        fichas.append({
            "employeeId": ficha.employeeId,
            "nombre": ficha.nombre,
            "position": ficha.position,
            "cumplimiento": vars(ficha.cumplimiento),
            "actividad": vars(ficha.actividad),
            "operativo": vars(ficha.operativo),
            "feedback": vars(ficha.feedback),
            "trayectoria": ficha.trayectoria,
            "cobertura": ficha.cobertura,
            "dimensionesTotales": ficha.dimensionesTotales,
        })

    return {"success": True, "data": {"departmentId": department_id, "fichas": fichas}}
