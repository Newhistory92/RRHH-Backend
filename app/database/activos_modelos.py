"""
Modelos de PC de referencia + scoring (subsistema 6). Un modelo es un conjunto
de umbrales minimos por categoria de componente; evaluar una PC contra un modelo
devuelve el porcentaje de requisitos cumplidos y el detalle por requisito.
Lee las specs crudas guardadas en Activo.specsJson al elegir del catalogo PCParts.
"""

import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional


CREATE_MODELO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoModeloPC' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoModeloPC (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        nombre      NVARCHAR(150) NOT NULL,
        descripcion NVARCHAR(500) NULL,
        activo      BIT           NOT NULL DEFAULT 1,
        createdAt   DATETIME2     NOT NULL,
        updatedAt   DATETIME2     NOT NULL
    );
END
"""

CREATE_REQUISITO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoModeloRequisito' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoModeloRequisito (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        modeloId    INT           NOT NULL,
        categoriaId INT           NOT NULL,
        campoSpec   NVARCHAR(50)  NOT NULL,
        valorMinimo FLOAT         NOT NULL,
        createdAt   DATETIME2     NOT NULL
    );
    CREATE INDEX IX_ActivoModeloRequisito_modeloId ON ActivoModeloRequisito (modeloId);
END
"""


# Campos numericos ofrecibles como umbral, por nombre de ActivoCategoria (S1).
# Derivado de las specs reales del catalogo PCParts verificadas contra la DB.
# Las categorias sin entrada aqui no ofrecen umbrales.
CAMPOS_SPEC_POR_CATEGORIA = {
    "CPU": [
        {"campo": "core_count", "etiqueta": "Núcleos", "unidad": ""},
        {"campo": "boost_clock", "etiqueta": "Frecuencia turbo", "unidad": "GHz"},
    ],
    "Memoria RAM": [
        {"campo": "modules", "etiqueta": "Capacidad total", "unidad": "GB"},
        {"campo": "speed", "etiqueta": "Velocidad", "unidad": "MHz"},
    ],
    "Tarjetas de Video": [
        {"campo": "memory", "etiqueta": "Memoria de video", "unidad": "GB"},
    ],
    "Almacenamiento": [
        {"campo": "capacity", "etiqueta": "Capacidad", "unidad": "GB"},
    ],
    "Fuentes de Alimentación": [
        {"campo": "wattage", "etiqueta": "Potencia", "unidad": "W"},
    ],
    "Placas Base": [
        {"campo": "max_memory", "etiqueta": "Memoria máxima", "unidad": "GB"},
        {"campo": "memory_slots", "etiqueta": "Slots de memoria", "unidad": ""},
    ],
}


def ensure_tables(db: Session) -> None:
    """Crea las tablas de modelos/requisitos y asegura Activo.specsJson.
    El ALTER va en su propio batch + commit: SQL Server compila el batch entero
    antes de ejecutarlo y fallaria si un statement posterior referenciara la
    columna recien creada dentro del mismo batch."""
    db.execute(text(CREATE_MODELO_SQL))
    db.execute(text(CREATE_REQUISITO_SQL))
    db.commit()
    db.execute(text("IF COL_LENGTH('Activo','specsJson') IS NULL ALTER TABLE Activo ADD specsJson NVARCHAR(MAX) NULL;"))
    db.commit()


def _valor_de_spec(specs_json: Optional[str], campo: str) -> Optional[float]:
    """Extrae el valor numerico de un campo del JSON de specs de PCParts.
    Devuelve None (= 'sin datos') si el JSON falta, esta corrupto, no tiene la
    clave, o el valor no es numerico -- nunca lanza excepcion.

    Campos tipo par (verificado contra datos reales del catalogo):
      - 'modules': [cantidad, capacidad] -> producto (ej. [2,16] = 32 GB totales)
      - cualquier otro par (ej. 'speed': [5,6000]) -> segundo elemento
    """
    if not specs_json:
        return None
    try:
        obj = json.loads(specs_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or campo not in obj:
        return None
    v = obj[campo]
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and len(v) == 2:
        a, b = v[0], v[1]
        if isinstance(a, bool) or isinstance(b, bool):
            return None
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        return float(a) * float(b) if campo == "modules" else float(b)
    return None


def campos_disponibles(db: Session) -> list[dict]:
    """CAMPOS_SPEC_POR_CATEGORIA resuelto con los ids reales de ActivoCategoria,
    para poblar los selects encadenados del frontend. Solo categorias vigentes
    y montables en PC."""
    rows = db.execute(text(
        "SELECT id, nombre FROM ActivoCategoria WHERE activo = 1 AND montableEnPC = 1 ORDER BY nombre"
    )).mappings().all()
    salida = []
    for r in rows:
        campos = CAMPOS_SPEC_POR_CATEGORIA.get(r["nombre"])
        if campos:
            salida.append({"categoriaId": r["id"], "categoriaNombre": r["nombre"], "campos": campos})
    return salida


def nombre_duplicado(db: Session, nombre: str, excluir_id: Optional[int] = None) -> bool:
    q = "SELECT id FROM ActivoModeloPC WHERE activo = 1 AND LOWER(nombre) = LOWER(:n)"
    params = {"n": nombre}
    if excluir_id:
        q += " AND id <> :id"
        params["id"] = excluir_id
    return db.execute(text(q), params).first() is not None


def listar_modelos(db: Session) -> list[dict]:
    """Modelos vigentes con la cantidad de requisitos de cada uno."""
    rows = db.execute(text("""
        SELECT m.id, m.nombre, m.descripcion,
               (SELECT COUNT(*) FROM ActivoModeloRequisito r WHERE r.modeloId = m.id) AS cantidadRequisitos
        FROM ActivoModeloPC m
        WHERE m.activo = 1
        ORDER BY m.nombre
    """)).mappings().all()
    return [{"id": r["id"], "nombre": r["nombre"], "descripcion": r["descripcion"],
             "cantidadRequisitos": r["cantidadRequisitos"]} for r in rows]


def _requisitos_de(db: Session, modelo_id: int) -> list[dict]:
    rows = db.execute(text("""
        SELECT r.id, r.categoriaId, c.nombre AS categoriaNombre, r.campoSpec, r.valorMinimo
        FROM ActivoModeloRequisito r
        INNER JOIN ActivoCategoria c ON r.categoriaId = c.id
        WHERE r.modeloId = :id
        ORDER BY c.nombre, r.campoSpec
    """), {"id": modelo_id}).mappings().all()
    salida = []
    for r in rows:
        meta = next((x for x in CAMPOS_SPEC_POR_CATEGORIA.get(r["categoriaNombre"], [])
                     if x["campo"] == r["campoSpec"]), None)
        salida.append({
            "id": r["id"], "categoriaId": r["categoriaId"], "categoriaNombre": r["categoriaNombre"],
            "campoSpec": r["campoSpec"],
            "etiqueta": meta["etiqueta"] if meta else r["campoSpec"],
            "unidad": meta["unidad"] if meta else "",
            "valorMinimo": float(r["valorMinimo"]),
        })
    return salida


def obtener_modelo(db: Session, modelo_id: int) -> Optional[dict]:
    r = db.execute(text(
        "SELECT id, nombre, descripcion FROM ActivoModeloPC WHERE id = :id AND activo = 1"
    ), {"id": modelo_id}).mappings().first()
    if not r:
        return None
    return {"id": r["id"], "nombre": r["nombre"], "descripcion": r["descripcion"],
            "requisitos": _requisitos_de(db, modelo_id)}


def crear_modelo(db: Session, nombre: str, descripcion: Optional[str]) -> int:
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoModeloPC (nombre, descripcion, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :desc, 1, :now, :now)
    """), {"nombre": nombre, "desc": descripcion, "now": now})
    return result.scalar()


def actualizar_modelo(db: Session, modelo_id: int, nombre: str, descripcion: Optional[str]) -> None:
    db.execute(text("""
        UPDATE ActivoModeloPC SET nombre = :nombre, descripcion = :desc, updatedAt = :now
        WHERE id = :id
    """), {"nombre": nombre, "desc": descripcion, "now": datetime.utcnow(), "id": modelo_id})


def baja_modelo(db: Session, modelo_id: int) -> None:
    db.execute(text("UPDATE ActivoModeloPC SET activo = 0, updatedAt = :now WHERE id = :id"),
               {"now": datetime.utcnow(), "id": modelo_id})


def requisito_duplicado(db: Session, modelo_id: int, categoria_id: int, campo_spec: str) -> bool:
    return db.execute(text("""
        SELECT id FROM ActivoModeloRequisito
        WHERE modeloId = :m AND categoriaId = :c AND campoSpec = :campo
    """), {"m": modelo_id, "c": categoria_id, "campo": campo_spec}).first() is not None


def agregar_requisito(db: Session, modelo_id: int, categoria_id: int,
                      campo_spec: str, valor_minimo: float) -> int:
    result = db.execute(text("""
        INSERT INTO ActivoModeloRequisito (modeloId, categoriaId, campoSpec, valorMinimo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:m, :c, :campo, :valor, :now)
    """), {"m": modelo_id, "c": categoria_id, "campo": campo_spec,
           "valor": valor_minimo, "now": datetime.utcnow()})
    return result.scalar()


def quitar_requisito(db: Session, modelo_id: int, requisito_id: int) -> bool:
    """Borra el requisito si pertenece a ese modelo. False si no existe/no coincide."""
    r = db.execute(text("SELECT id FROM ActivoModeloRequisito WHERE id = :id AND modeloId = :m"),
                   {"id": requisito_id, "m": modelo_id}).first()
    if not r:
        return False
    db.execute(text("DELETE FROM ActivoModeloRequisito WHERE id = :id"), {"id": requisito_id})
    return True


def evaluar_pc(db: Session, pc_id: int, modelo_id: int) -> dict:
    """Evalua los componentes instalados en pc_id contra los requisitos del modelo.
    Por cada requisito toma el MEJOR valor entre los componentes de esa categoria
    (ej. si hay 2 discos, el de mayor capacidad). Requisitos sin datos evaluables
    se excluyen del denominador del score en vez de contar como incumplidos."""
    requisitos = _requisitos_de(db, modelo_id)
    detalle = []
    cumplidos = 0
    sin_datos = 0
    for req in requisitos:
        comps = db.execute(text("""
            SELECT specsJson FROM Activo
            WHERE activo = 1 AND pcPadreId = :pc AND categoriaId = :cat
        """), {"pc": pc_id, "cat": req["categoriaId"]}).mappings().all()
        valores = [v for v in (_valor_de_spec(c["specsJson"], req["campoSpec"]) for c in comps)
                   if v is not None]
        if not valores:
            estado = "sin_datos"
            valor_real = None
            sin_datos += 1
        else:
            valor_real = max(valores)
            if valor_real >= req["valorMinimo"]:
                estado = "cumple"
                cumplidos += 1
            else:
                estado = "no_cumple"
        detalle.append({**req, "valorReal": valor_real, "estado": estado})

    total = len(requisitos)
    evaluables = total - sin_datos
    score = round(cumplidos / evaluables * 100) if evaluables > 0 else None
    return {"score": score, "total": total, "cumplidos": cumplidos,
            "sinDatos": sin_datos, "requisitos": detalle}
