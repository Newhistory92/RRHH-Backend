"""
Chatbot de RRHH conectado a la base de datos.

POST /chat  — recibe el historial de la conversacion y devuelve la siguiente
             respuesta del asistente. Claude usa tool use para consultar datos
             reales de la base antes de responder.

Las herramientas solo leen la base (SELECT). Ningun tool modifica datos.
"""

import json
import logging
import os
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_any_auth
from app.database.database import SessionLocal

log = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

SOLO_AUTH = Depends(require_any_auth)


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
    role: str          # "user" | "assistant"
    content: str


class PeticionChat(BaseModel):
    messages: list[MensajeChat]


# ---------------------------------------------------------------------------
# Definiciones de herramientas para Claude
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "estadisticas_generales",
        "description": (
            "Devuelve estadísticas globales de la organización: total de empleados, "
            "distribución por género, distribución por estado (activo/inactivo/jubilado), "
            "cantidad de departamentos y cantidad con licencia activa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "buscar_empleado",
        "description": (
            "Busca uno o varios empleados por nombre o apellido (búsqueda parcial). "
            "Devuelve datos personales, departamento, oficina, cargo y contrato. "
            "Usar cuando el usuario pregunta por una persona específica."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre o apellido a buscar (parcial, sin distinción de mayúsculas).",
                }
            },
            "required": ["nombre"],
        },
    },
    {
        "name": "empleados_por_departamento",
        "description": (
            "Lista los empleados de un departamento específico con su nombre, cargo, "
            "tipo de contrato y estado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "departamento": {
                    "type": "string",
                    "description": "Nombre o parte del nombre del departamento.",
                }
            },
            "required": ["departamento"],
        },
    },
    {
        "name": "documentos_empleado",
        "description": (
            "Lista los documentos del legajo de un empleado (DNI, resoluciones, "
            "certificados, etc.) dado su ID numérico."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "empleado_id": {
                    "type": "integer",
                    "description": "ID numérico del empleado.",
                }
            },
            "required": ["empleado_id"],
        },
    },
    {
        "name": "empleados_con_licencia",
        "description": (
            "Devuelve la lista de empleados que actualmente tienen una licencia activa "
            "o pendiente, con el tipo y fechas de la licencia."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "listar_departamentos",
        "description": (
            "Lista todos los departamentos de la organización con la cantidad de "
            "empleados en cada uno."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "ausencias_recientes",
        "description": (
            "Devuelve las ausencias registradas en los últimos N días (por defecto 30). "
            "Incluye nombre del empleado, fecha y motivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "description": "Cantidad de días hacia atrás a consultar. Por defecto 30.",
                    "default": 30,
                }
            },
            "required": [],
        },
    },
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
        SELECT e.id, e.name, e.dni, e.email, e.gender, e.status,
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


def _documentos_empleado(db: Session, empleado_id: int) -> dict:
    empleado = db.execute(text(
        "SELECT id, name FROM Employee WHERE id = :id"
    ), {"id": empleado_id}).mappings().first()
    if not empleado:
        return {"error": f"No existe el empleado con id {empleado_id}"}
    docs = db.execute(text("""
        SELECT tipo, descripcion, fileName, createdAt
        FROM EmployeeDocument
        WHERE employeeId = :id AND activo = 1
        ORDER BY createdAt DESC
    """), {"id": empleado_id}).mappings().all()
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


def _ausencias_recientes(db: Session, dias: int = 30) -> list[dict]:
    filas = db.execute(text("""
        SELECT e.name, a.fecha, a.motivo
        FROM Ausencia a
        JOIN Employee e ON a.employeeId = e.id
        WHERE a.fecha >= DATEADD(DAY, :neg_dias, GETDATE())
        ORDER BY a.fecha DESC
    """), {"neg_dias": -abs(dias)}).mappings().all()
    return [dict(f) for f in filas]


def ejecutar_tool(nombre: str, inputs: dict, db: Session) -> Any:
    """Despacha la herramienta y retorna el resultado como dato Python."""
    if nombre == "estadisticas_generales":
        return _estadisticas_generales(db)
    if nombre == "buscar_empleado":
        return _buscar_empleado(db, inputs["nombre"])
    if nombre == "empleados_por_departamento":
        return _empleados_por_departamento(db, inputs["departamento"])
    if nombre == "documentos_empleado":
        return _documentos_empleado(db, inputs["empleado_id"])
    if nombre == "empleados_con_licencia":
        return _empleados_con_licencia(db)
    if nombre == "listar_departamentos":
        return _listar_departamentos(db)
    if nombre == "ausencias_recientes":
        return _ausencias_recientes(db, inputs.get("dias", 30))
    return {"error": f"Herramienta desconocida: {nombre}"}


# ---------------------------------------------------------------------------
# Prompt de sistema
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres el asistente de Recursos Humanos de la organización.
Tienes acceso directo a la base de datos de RRHH mediante herramientas.
Cuando el usuario pregunta sobre empleados, estadísticas, documentos, licencias
o departamentos, SIEMPRE usa las herramientas para obtener datos reales antes
de responder. No inventes datos.

Responde en español, de forma clara y concisa. Si los resultados son una lista
larga, muestra un resumen y ofrece más detalle si se necesita.
Nunca expongas IDs internos al usuario salvo que los pida explícitamente."""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("", dependencies=[SOLO_AUTH])
def chat(peticion: PeticionChat, db: Session = Depends(get_db)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY no configurada en el servidor.",
        )

    cliente = anthropic.Anthropic(api_key=api_key)

    # Convertir el historial al formato que espera la API de Anthropic
    historial = [{"role": m.role, "content": m.content} for m in peticion.messages]

    # Agentic loop: Claude puede pedir varias herramientas en cadena
    MAX_ITERACIONES = 10
    for _ in range(MAX_ITERACIONES):
        respuesta = cliente.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=historial,
        )

        # Si Claude terminó sin pedir herramientas, devolver la respuesta
        if respuesta.stop_reason == "end_turn":
            texto = next(
                (b.text for b in respuesta.content if hasattr(b, "text")),
                "",
            )
            return {"result": texto}

        # Claude pidió herramientas: ejecutarlas y agregar resultados al historial
        if respuesta.stop_reason == "tool_use":
            # Agregar la respuesta de Claude (con los tool_use) al historial
            historial.append({
                "role": "assistant",
                "content": respuesta.content,
            })

            # Construir el bloque tool_result para cada herramienta solicitada
            resultados = []
            for bloque in respuesta.content:
                if bloque.type != "tool_use":
                    continue
                try:
                    dato = ejecutar_tool(bloque.name, bloque.input, db)
                except Exception as e:
                    log.exception("Error ejecutando tool '%s'", bloque.name)
                    dato = {"error": str(e)}

                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": json.dumps(dato, default=str, ensure_ascii=False),
                })

            historial.append({"role": "user", "content": resultados})
            continue

        # Cualquier otro stop_reason (max_tokens, etc.)
        break

    raise HTTPException(
        status_code=500,
        detail="El asistente no pudo completar la respuesta.",
    )
