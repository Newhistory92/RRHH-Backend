"""
Banco de preguntas de Feedback 360 y modelo de respuestas individuales.

Reemplaza el modelo agregado anterior (Feedback/Respuesta/FeedbackEvaluacion,
que siguen existiendo en la base pero sin uso desde este modulo) por un
banco de preguntas fijo mas una tabla de respuestas individuales, para
soportar escala 1-5, preguntas de texto libre, y vinculo directo a
oficina/departamento/periodo por cada respuesta.
"""

import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLES_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'Pregunta' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Pregunta (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        texto             NVARCHAR(500)  NOT NULL,
        categoria         NVARCHAR(100)  NOT NULL,
        tipo              NVARCHAR(20)   NOT NULL,
        opcionesEscala    NVARCHAR(500)  NULL,
        soloLiderazgo     BIT            NOT NULL DEFAULT 0,
        esAmbienteGeneral BIT            NOT NULL DEFAULT 0,
        activo            BIT            NOT NULL DEFAULT 1,
        createdAt         DATETIME2      NOT NULL
    );
END

IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'RespuestaFeedback' AND xtype = 'U'
)
BEGIN
    CREATE TABLE RespuestaFeedback (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        preguntaId          INT            NOT NULL REFERENCES Pregunta(id),
        evaluadorEmployeeId INT            NOT NULL,
        evaluadoEmployeeId  INT            NULL,
        officeId            INT            NULL,
        departmentId        INT            NULL,
        periodo             DATE           NOT NULL,
        valorEscala         INT            NULL,
        textoLibre          NVARCHAR(MAX)  NULL,
        createdAt           DATETIME2      NOT NULL
    );
    CREATE INDEX IX_RespuestaFeedback_periodo ON RespuestaFeedback (periodo);
    CREATE INDEX IX_RespuestaFeedback_evaluado ON RespuestaFeedback (evaluadoEmployeeId);
END
"""

ESCALA_ESTANDAR = ["Siempre", "Casi siempre", "Algunas veces", "Rara vez", "Nunca"]

# (texto, categoria, tipo, opcionesEscala | None, soloLiderazgo, esAmbienteGeneral)
PREGUNTAS_BASE = [
    # 1. Respeto y convivencia
    ("¿La persona trata a sus compañeros con respeto?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Mantiene un trato cordial durante la jornada laboral?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Has presenciado conductas inapropiadas por parte de esta persona?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Comparte información importante con el equipo?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Genera conflictos innecesarios?", "Respeto y convivencia", "escala", None, False, False),
    # 3. Comunicación
    ("¿Escucha las opiniones de los demás?", "Comunicación", "escala", None, False, False),
    ("¿Expresa sus ideas de forma respetuosa?", "Comunicación", "escala", None, False, False),
    ("¿Acepta críticas constructivas?", "Comunicación", "escala", None, False, False),
    # 4. Responsabilidad
    ("¿Cumple con sus tareas en tiempo y forma?", "Responsabilidad", "escala", None, False, False),
    ("¿Es confiable cuando se le asigna una tarea?", "Responsabilidad", "escala", None, False, False),
    ("¿Su trabajo genera retrabajos para otros?", "Responsabilidad", "escala", None, False, False),
    # 5. Profesionalismo
    ("¿Respeta horarios y normas internas?", "Profesionalismo", "escala", None, False, False),
    ("¿Mantiene una actitud profesional?", "Profesionalismo", "escala", None, False, False),
    # 6. Liderazgo (solo para jefes)
    ("¿Brinda instrucciones claras?", "Liderazgo", "escala", None, True, False),
    ("¿Escucha las inquietudes del equipo?", "Liderazgo", "escala", None, True, False),
    ("¿Distribuye el trabajo de manera justa?", "Liderazgo", "escala", None, True, False),
    ("¿Reconoce el buen desempeño?", "Liderazgo", "escala", None, True, False),
    ("¿Resuelve conflictos de manera adecuada?", "Liderazgo", "escala", None, True, False),
    # 7. Riesgos laborales
    ("¿Alguna persona del equipo genera un ambiente tenso?", "Riesgos laborales", "escala", None, False, False),
    ("¿Te sentís cómodo trabajando con esta persona?", "Riesgos laborales", "escala", None, False, False),
    ("¿Evitás interactuar con esta persona cuando es posible?", "Riesgos laborales", "escala", None, False, False),
    ("¿Considerás que esta persona afecta negativamente al equipo?", "Riesgos laborales", "escala", None, False, False),
    # 8. Conductas de riesgo
    ("¿Has observado faltas de respeto hacia compañeros?", "Conductas de riesgo", "escala", None, False, False),
    ("¿Has observado conductas intimidantes o agresivas?", "Conductas de riesgo", "escala", None, False, False),
    ("¿Creés que esta persona discrimina o hace comentarios ofensivos?", "Conductas de riesgo", "escala", None, False, False),
    # 9. Confianza (escalas propias)
    ("¿Confiarías en esta persona para trabajar en una tarea importante?", "Confianza", "escala",
        ["Totalmente", "Sí", "Parcialmente", "Poco", "No"], False, False),
    ("¿Volverías a elegir trabajar con esta persona?", "Confianza", "escala",
        ["Sí, sin dudas", "Sí", "Me es indiferente", "Preferiría que no", "Definitivamente no"], False, False),
    # 10. Preguntas abiertas
    ("¿Qué fortalezas destacás de esta persona?", "Preguntas abiertas", "texto_libre", None, False, False),
    ("¿Qué aspecto debería mejorar?", "Preguntas abiertas", "texto_libre", None, False, False),
    ("¿Hay algo que Recursos Humanos o la dirección debería conocer?", "Preguntas abiertas", "texto_libre", None, False, False),
]

PREGUNTAS_AMBIENTE_GENERAL = [
    ("¿Te sentís valorado en tu trabajo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Existe favoritismo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís escuchado?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís cómodo expresando desacuerdos?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Existe colaboración entre áreas?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís sobrecargado de trabajo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Has pensado en renunciar por el ambiente laboral?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Recomendarías esta oficina como lugar para trabajar?", "Ambiente laboral general", "escala", None, False, True),
]


def ensure_table(db: Session) -> None:
    """Crea Pregunta y RespuestaFeedback si no existen, y siembra el
    banco de preguntas solo si Pregunta esta vacia (no duplica en cada
    llamada ni pisa preguntas que RRHH haya desactivado a mano)."""
    db.execute(text(CREATE_TABLES_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM Pregunta")).mappings().first()
    if count["c"] == 0:
        now = datetime.utcnow()
        for texto, categoria, tipo, opciones, solo_lid, ambiente in PREGUNTAS_BASE + PREGUNTAS_AMBIENTE_GENERAL:
            opciones_final = opciones if opciones is not None else (ESCALA_ESTANDAR if tipo == "escala" else None)
            opciones_json = json.dumps(opciones_final, ensure_ascii=False) if opciones_final is not None else None
            db.execute(text("""
                INSERT INTO Pregunta
                    (texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral, activo, createdAt)
                VALUES
                    (:texto, :categoria, :tipo, :opciones, :solo_lid, :ambiente, 1, :now)
            """), {
                "texto": texto, "categoria": categoria, "tipo": tipo,
                "opciones": opciones_json, "solo_lid": solo_lid, "ambiente": ambiente, "now": now,
            })
        db.commit()


def get_preguntas(db: Session, solo_liderazgo: bool | None = None, es_ambiente_general: bool | None = None) -> list[dict]:
    """Lista preguntas activas, con filtros opcionales por soloLiderazgo / esAmbienteGeneral."""
    query = "SELECT id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral FROM Pregunta WHERE activo = 1"
    params = {}
    if solo_liderazgo is not None:
        query += " AND soloLiderazgo = :solo_lid"
        params["solo_lid"] = 1 if solo_liderazgo else 0
    if es_ambiente_general is not None:
        query += " AND esAmbienteGeneral = :ambiente"
        params["ambiente"] = 1 if es_ambiente_general else 0
    query += " ORDER BY categoria ASC, id ASC"

    rows = db.execute(text(query), params).mappings().all()
    result = []
    for r in rows:
        row = dict(r)
        row["opcionesEscala"] = json.loads(row["opcionesEscala"]) if row["opcionesEscala"] else None
        row["soloLiderazgo"] = bool(row["soloLiderazgo"])
        row["esAmbienteGeneral"] = bool(row["esAmbienteGeneral"])
        result.append(row)
    return result
