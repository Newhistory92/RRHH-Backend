"""
Chatbot de RRHH conectado a la base de datos via Google Gemini.

POST /chat  — recibe el historial de la conversacion y devuelve la siguiente
             respuesta del asistente. Gemini usa function calling para consultar
             datos reales de la base antes de responder.

Las herramientas solo leen la base (SELECT). Ningun tool modifica datos.
Requiere GOOGLE_GENERATIVE_AI_API_KEY en el .env.
"""

import json
import logging
import os
from datetime import date, timedelta
from typing import Any

from google import genai
from google.genai import types as gtypes
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.database import SessionLocal

log = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

SOLO_AUTH = Depends(require_permission("ia.usar"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------

class MensajeChat(BaseModel):
    role: str      # "user" | "assistant"
    content: str


class PeticionChat(BaseModel):
    messages: list[MensajeChat]


# ---------------------------------------------------------------------------
# Definiciones de herramientas para Gemini
# ---------------------------------------------------------------------------

TOOLS_GEMINI = [
    gtypes.FunctionDeclaration(
        name="estadisticas_generales",
        description=(
            "Devuelve estadísticas globales de la organización: total de empleados, "
            "distribución por género, distribución por estado, cantidad de departamentos "
            "y cantidad con licencia activa."
        ),
        parameters=gtypes.Schema(type=gtypes.Type.OBJECT, properties={}),
    ),
    gtypes.FunctionDeclaration(
        name="buscar_empleado",
        description=(
            "Busca uno o varios empleados por nombre o apellido (búsqueda parcial). "
            "Devuelve datos personales (incluyendo fecha de nacimiento, teléfono y "
            "el ID del reloj biométrico), departamento, oficina, cargo y contrato."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "nombre": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Nombre o apellido a buscar (parcial).",
                )
            },
            required=["nombre"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="empleados_por_departamento",
        description="Lista los empleados de un departamento con su nombre, cargo, contrato y estado.",
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "departamento": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Nombre o parte del nombre del departamento.",
                )
            },
            required=["departamento"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="documentos_empleado",
        description=(
            "Lista los documentos del legajo de un empleado. Se lo puede buscar "
            "por nombre (lo más común) o por ID numérico si ya se conoce."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "nombre": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Nombre o apellido del empleado (búsqueda parcial).",
                ),
                "empleado_id": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="ID numérico del empleado, si ya se conoce.",
                ),
            },
        ),
    ),
    gtypes.FunctionDeclaration(
        name="empleados_con_licencia",
        description="Lista los empleados con licencia activa o pendiente, con tipo y fechas.",
        parameters=gtypes.Schema(type=gtypes.Type.OBJECT, properties={}),
    ),
    gtypes.FunctionDeclaration(
        name="listar_departamentos",
        description="Lista todos los departamentos con la cantidad de empleados en cada uno.",
        parameters=gtypes.Schema(type=gtypes.Type.OBJECT, properties={}),
    ),
    gtypes.FunctionDeclaration(
        name="ausencias_recientes",
        description=(
            "Ausencias registradas en los últimos N días (default 30). Incluye "
            "empleado, fecha y motivo. Si se da 'nombre', filtra a las ausencias "
            "de ese empleado en particular."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "dias": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="Cantidad de días hacia atrás. Por defecto 30.",
                ),
                "nombre": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Nombre o apellido del empleado, para filtrar a uno solo.",
                ),
            },
        ),
    ),
    gtypes.FunctionDeclaration(
        name="estadisticas_tardanzas",
        description=(
            "Estadísticas de llegadas tarde de un empleado: cuántas veces llegó tarde, "
            "cuántas quedaron perdonadas por el margen de tolerancia y cuántas lo "
            "superaron, el promedio de minutos de atraso y el detalle de las peores "
            "jornadas. Usa esto para cualquier pregunta sobre tardanzas, puntualidad "
            "o llegadas tarde de una persona."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "nombre": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Nombre o apellido del empleado (búsqueda parcial).",
                ),
                "dias": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="Cantidad de días hacia atrás a analizar. Por defecto 90.",
                ),
            },
            required=["nombre"],
        ),
    ),
]


# ---------------------------------------------------------------------------
# Implementación de las herramientas (solo SELECT)
# ---------------------------------------------------------------------------

def _estadisticas_generales(db: Session) -> dict:
    total = db.execute(text("SELECT COUNT(*) FROM Employee")).scalar() or 0
    por_genero = db.execute(text(
        "SELECT gender, COUNT(*) as cnt FROM Employee GROUP BY gender"
    )).mappings().all()
    por_estado = db.execute(text(
        "SELECT status, COUNT(*) as cnt FROM Employee WHERE status IS NOT NULL GROUP BY status"
    )).mappings().all()
    departamentos = db.execute(text("SELECT COUNT(*) FROM Department")).scalar() or 0
    con_licencia = db.execute(text(
        "SELECT COUNT(DISTINCT employeeId) FROM License "
        "WHERE status IN ('activa','pendiente') AND endDate >= GETDATE()"
    )).scalar() or 0
    return {
        "total_empleados": total,
        "por_genero": [{"genero": r["gender"] or "Sin dato", "cantidad": r["cnt"]} for r in por_genero],
        "por_estado": [{"estado": r["status"], "cantidad": r["cnt"]} for r in por_estado],
        "total_departamentos": departamentos,
        "empleados_con_licencia_activa": con_licencia,
    }


def _buscar_empleado(db: Session, nombre: str) -> list[dict]:
    filas = db.execute(text("""
        SELECT e.id, e.name, e.dni, e.email, e.phone, e.birthDate, e.gender,
               e.status, e.biometricoId,
               d.nombre AS departamento, o.nombre AS oficina,
               c.tipoContrato, c.categoria, c.position AS cargo
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.name LIKE :patron
        ORDER BY e.name
    """), {"patron": f"%{nombre}%"}).mappings().all()
    return [dict(f) for f in filas]


def _empleados_por_departamento(db: Session, departamento: str) -> list[dict]:
    filas = db.execute(text("""
        SELECT e.id, e.name, e.status,
               c.tipoContrato, c.categoria, c.position AS cargo,
               o.nombre AS oficina
        FROM Employee e
        JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE d.nombre LIKE :patron
        ORDER BY e.name
    """), {"patron": f"%{departamento}%"}).mappings().all()
    return [dict(f) for f in filas]


def _documentos_empleado(db: Session, nombre: str | None = None,
                         empleado_id: int | None = None) -> dict:
    """
    Resuelve por nombre (lo que pide un uso normal del chat) o por ID directo
    si ya se conoce, por ejemplo porque una tool anterior en la misma cadena
    ya lo devolvio. Sin ninguno de los dos no hay forma de saber a quien
    buscar, asi que se le devuelve el error a Gemini para que le pregunte.
    """
    if empleado_id is not None:
        empleado = db.execute(text(
            "SELECT id, name FROM Employee WHERE id = :id"
        ), {"id": empleado_id}).mappings().first()
        if not empleado:
            return {"error": f"No existe el empleado con id {empleado_id}"}
    elif nombre:
        empleado = _resolver_empleado_unico(db, nombre)
        if "error" in empleado or empleado.get("ambiguo"):
            return empleado
    else:
        return {"error": "Se necesita el nombre o el ID del empleado."}

    docs = db.execute(text("""
        SELECT tipo, descripcion, fileName, createdAt
        FROM EmployeeDocument
        WHERE employeeId = :id AND activo = 1
        ORDER BY createdAt DESC
    """), {"id": empleado["id"]}).mappings().all()
    return {
        "empleado": dict(empleado),
        "documentos": [dict(d) for d in docs],
    }


def _empleados_con_licencia(db: Session) -> list[dict]:
    filas = db.execute(text("""
        SELECT e.id, e.name, l.type, l.startDate, l.endDate, l.status
        FROM License l
        JOIN Employee e ON l.employeeId = e.id
        WHERE l.status IN ('activa','pendiente') AND l.endDate >= GETDATE()
        ORDER BY l.startDate
    """)).mappings().all()
    return [dict(f) for f in filas]


def _listar_departamentos(db: Session) -> list[dict]:
    filas = db.execute(text("""
        SELECT d.nombre, COUNT(e.id) AS empleados
        FROM Department d
        LEFT JOIN Employee e ON e.departmentId = d.id
        GROUP BY d.nombre
        ORDER BY d.nombre
    """)).mappings().all()
    return [dict(f) for f in filas]


def _resolver_empleado_unico(db: Session, nombre: str) -> dict:
    """
    Busca por nombre parcial y exige una sola coincidencia: las estadisticas
    de tardanzas son por persona, asi que un nombre ambiguo (dos "Rojo") no
    puede resolverse solo -se le devuelve la lista a Gemini para que
    repregunte en vez de adivinar cual de los dos quiso decir el usuario.
    """
    filas = db.execute(text("""
        SELECT id, name FROM Employee WHERE name LIKE :patron ORDER BY name
    """), {"patron": f"%{nombre}%"}).mappings().all()
    if not filas:
        return {"error": f"No se encontró ningún empleado que coincida con '{nombre}'."}
    if len(filas) > 1:
        return {
            "ambiguo": True,
            "coincidencias": [dict(f) for f in filas],
            "mensaje": "Hay varios empleados que coinciden con ese nombre. "
                       "Pedile al usuario que aclare cuál, o usa el ID.",
        }
    return dict(filas[0])


def _tardanzas_empleado(db: Session, nombre: str, dias: int = 90,
                        hoy: date | None = None) -> dict:
    """
    Tardanzas de un empleado en una ventana de dias hacia atras.

    "Tarde" se mide contra Horario.horaInicio, no contra el saldo del dia:
    saldoDia negativo puede venir de un permiso sin banco, nada que ver con
    la hora de entrada. toleranciaEntradaUsada/abusoEntrada, en cambio, ya
    los computa el motor de asistencia (asistencia_calc._ajustar_por_tolerancia)
    exactamente sobre el desvio de entrada, asi que se reusan tal cual en vez
    de re-derivar el mismo calculo en SQL.
    """
    empleado = _resolver_empleado_unico(db, nombre)
    if "error" in empleado or empleado.get("ambiguo"):
        return empleado

    horario = db.execute(text("""
        SELECT h.horaInicio FROM Employee e
        JOIN Horario h ON e.cronogramaId = h.id
        WHERE e.id = :id
    """), {"id": empleado["id"]}).mappings().first()
    if horario is None:
        return {
            "empleado": empleado,
            "error": "Este empleado no tiene un horario asignado, no se puede "
                     "calcular si llegó tarde.",
        }

    hasta = hoy or date.today()
    desde = hasta - timedelta(days=abs(dias))
    hora_inicio = float(horario["horaInicio"])

    filas = db.execute(text("""
        SELECT fecha, entrada, toleranciaEntradaUsada, abusoEntrada
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
              AND entrada IS NOT NULL
        ORDER BY fecha
    """), {"emp": empleado["id"], "desde": desde, "hasta": hasta}).mappings().all()

    tardanzas = []
    for f in filas:
        entrada = f["entrada"]
        hora_decimal = entrada.hour + entrada.minute / 60 + entrada.second / 3600
        minutos = round((hora_decimal - hora_inicio) * 60)
        if minutos > 0:
            fecha = f["fecha"]
            tardanzas.append({
                "fecha": fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha),
                "minutosTarde": minutos,
                "dentroDelMargen": bool(f["toleranciaEntradaUsada"]),
            })

    dentro_margen = sum(1 for t in tardanzas if t["dentroDelMargen"])
    promedio = round(sum(t["minutosTarde"] for t in tardanzas) / len(tardanzas), 1) if tardanzas else 0.0
    peores = sorted(tardanzas, key=lambda t: -t["minutosTarde"])[:10]

    return {
        "empleado": empleado,
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "jornadasConMarcacion": len(filas),
        "totalTardanzas": len(tardanzas),
        "tardanzasDentroDelMargen": dentro_margen,
        "tardanzasFueraDelMargen": len(tardanzas) - dentro_margen,
        "promedioMinutosTarde": promedio,
        "peoresJornadas": peores,
    }


def _ausencias_recientes(db: Session, dias: int = 30,
                         nombre: str | None = None) -> list[dict] | dict:
    # La columna se llama "reason" (ver prisma/schema.prisma model Ausencia
    # en el frontend, que es quien crea esta tabla). Se alias a "motivo" para
    # que la clave que ve Gemini se mantenga en castellano.
    empleado_id = None
    if nombre:
        empleado = _resolver_empleado_unico(db, nombre)
        if "error" in empleado or empleado.get("ambiguo"):
            return empleado
        empleado_id = empleado["id"]

    filas = db.execute(text(f"""
        SELECT e.name, a.fecha, a.reason AS motivo
        FROM Ausencia a
        JOIN Employee e ON a.employeeId = e.id
        WHERE a.fecha >= DATEADD(DAY, :neg_dias, GETDATE())
              {"AND a.employeeId = :emp" if empleado_id is not None else ""}
        ORDER BY a.fecha DESC
    """), {"neg_dias": -abs(dias), **({"emp": empleado_id} if empleado_id is not None else {})}
    ).mappings().all()
    return [dict(f) for f in filas]


def ejecutar_tool(nombre: str, args: dict, db: Session) -> Any:
    if nombre == "estadisticas_generales":
        return _estadisticas_generales(db)
    if nombre == "buscar_empleado":
        return _buscar_empleado(db, args["nombre"])
    if nombre == "empleados_por_departamento":
        return _empleados_por_departamento(db, args["departamento"])
    if nombre == "documentos_empleado":
        eid = args.get("empleado_id")
        return _documentos_empleado(
            db, nombre=args.get("nombre"),
            empleado_id=int(eid) if eid is not None else None,
        )
    if nombre == "empleados_con_licencia":
        return _empleados_con_licencia(db)
    if nombre == "listar_departamentos":
        return _listar_departamentos(db)
    if nombre == "ausencias_recientes":
        return _ausencias_recientes(db, int(args.get("dias", 30)), args.get("nombre"))
    if nombre == "estadisticas_tardanzas":
        return _tardanzas_empleado(db, args["nombre"], int(args.get("dias", 90)))
    return {"error": f"Herramienta desconocida: {nombre}"}


# ---------------------------------------------------------------------------
# Prompt de sistema
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres el asistente de Recursos Humanos de la organización. "
    "Tienes acceso directo a la base de datos de RRHH mediante herramientas. "
    "Cuando el usuario pregunta sobre empleados, estadísticas, documentos, licencias, "
    "tardanzas, puntualidad o departamentos, SIEMPRE usa las herramientas para obtener "
    "datos reales antes de responder. No inventes datos. "
    "Si estadisticas_tardanzas devuelve 'ambiguo', no elijas por tu cuenta: pedile al "
    "usuario que aclare cuál de las coincidencias quiso decir. "
    "Responde en español, de forma clara y concisa. Si los resultados son una lista "
    "larga, muestra un resumen y ofrece más detalle si se necesita. "
    "Nunca expongas IDs internos al usuario salvo que los pida explícitamente."
)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("", dependencies=[SOLO_AUTH])
def chat(peticion: PeticionChat, db: Session = Depends(get_db)):
    api_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_GENERATIVE_AI_API_KEY no configurada en el servidor.",
        )

    cliente = genai.Client(api_key=api_key)

    # Convertir historial al formato de Gemini
    # Gemini usa "model" en lugar de "assistant"
    historial: list[gtypes.ContentUnion] = []
    for m in peticion.messages[:-1]:
        rol = "model" if m.role == "assistant" else "user"
        historial.append(gtypes.Content(role=rol, parts=[gtypes.Part(text=m.content)]))

    ultimo = peticion.messages[-1]
    config = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[gtypes.Tool(function_declarations=TOOLS_GEMINI)],
    )

    # Agentic loop: Gemini puede pedir varias herramientas en cadena
    MAX_ITERACIONES = 10
    contenido_actual: gtypes.ContentUnion = gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=ultimo.content)],
    )

    for _ in range(MAX_ITERACIONES):
        historial.append(contenido_actual)

        respuesta = cliente.models.generate_content(
            model="gemini-2.5-flash",
            contents=historial,
            config=config,
        )

        candidato = respuesta.candidates[0]
        historial.append(candidato.content)

        # Recopilar function calls de esta respuesta
        llamadas = [
            p.function_call
            for p in candidato.content.parts
            if p.function_call is not None
        ]

        if not llamadas:
            # Gemini terminó: extraer texto
            texto = "".join(
                p.text for p in candidato.content.parts
                if p.text is not None
            )
            return {"result": texto}

        # Ejecutar herramientas y preparar el siguiente turno
        partes_resultado = []
        for fc in llamadas:
            try:
                dato = ejecutar_tool(fc.name, dict(fc.args), db)
            except Exception as e:
                log.exception("Error ejecutando tool '%s'", fc.name)
                dato = {"error": str(e)}

            partes_resultado.append(
                gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        name=fc.name,
                        response={"result": json.dumps(dato, default=str, ensure_ascii=False)},
                    )
                )
            )

        contenido_actual = gtypes.Content(role="user", parts=partes_resultado)

    raise HTTPException(
        status_code=500,
        detail="El asistente no pudo completar la respuesta.",
    )
