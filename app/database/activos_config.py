"""
Configuracion y catalogos del Sistema de Activos (subsistema 1).
Cuatro tablas de metadata que el resto del modulo referencia:
ActivoCategoria (taxonomia unificada), ActivoFabricante, ActivoProveedor,
ActivoEstado. Creacion + seed idempotente via ensure_tables.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


VALID_GRUPOS = {"Equipo", "Componente", "Accesorio", "Mobiliario"}


CREATE_CATEGORIA_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoCategoria' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoCategoria (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        nombre        NVARCHAR(150) NOT NULL,
        grupo         NVARCHAR(20)  NOT NULL,
        montableEnPC  BIT           NOT NULL DEFAULT 0,
        requiereSerie BIT           NOT NULL DEFAULT 0,
        vidaUtilAnios INT           NULL,
        activo        BIT           NOT NULL DEFAULT 1,
        createdAt     DATETIME2     NOT NULL,
        updatedAt     DATETIME2     NOT NULL
    );
END
"""

CREATE_FABRICANTE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoFabricante' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoFabricante (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(150) NOT NULL,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

CREATE_PROVEEDOR_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoProveedor' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoProveedor (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(150) NOT NULL,
        contacto  NVARCHAR(300) NULL,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

CREATE_ESTADO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoEstado' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoEstado (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(50)  NOT NULL,
        codigo    NVARCHAR(30)  NOT NULL,
        orden     INT           NOT NULL DEFAULT 0,
        esCore    BIT           NOT NULL DEFAULT 0,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

# (nombre, grupo, montableEnPC)
_SEED_CATEGORIAS = [
    ("CPU", "Componente", 1),
    ("Disipadores CPU", "Componente", 1),
    ("Placas Base", "Componente", 1),
    ("Memoria RAM", "Componente", 1),
    ("Almacenamiento", "Componente", 1),
    ("Tarjetas de Video", "Componente", 1),
    ("Gabinetes", "Componente", 1),
    ("Fuentes de Alimentación", "Componente", 1),
    ("Unidades Ópticas", "Componente", 1),
    ("Sistemas Operativos", "Componente", 1),
    ("Almacenamiento Externo", "Componente", 0),
    ("Tarjetas de Sonido", "Componente", 1),
    ("Adaptadores de Red Cableados", "Componente", 1),
    ("Adaptadores de Red Inalámbricos", "Componente", 1),
    ("PC", "Equipo", 0),
    ("Monitor", "Equipo", 0),
    ("UPS", "Accesorio", 0),
    ("Impresoras", "Accesorio", 0),
    ("Escáneres", "Accesorio", 0),
    ("Fotocopiadoras", "Accesorio", 0),
]

# (nombre, codigo)
_SEED_ESTADOS = [
    ("Disponible", "disponible"),
    ("Asignado", "asignado"),
    ("En reparación", "en_reparacion"),
    ("Dañado", "danado"),
    ("En depósito", "en_deposito"),
    ("Prestado", "prestado"),
    ("En garantía", "en_garantia"),
    ("Dado de baja", "dado_de_baja"),
    ("Extraviado", "extraviado"),
    ("Robado", "robado"),
]


def ensure_tables(db: Session) -> None:
    """Crea las 4 tablas de config si no existen y las siembra si estan vacias."""
    db.execute(text(CREATE_CATEGORIA_SQL))
    db.execute(text(CREATE_FABRICANTE_SQL))
    db.execute(text(CREATE_PROVEEDOR_SQL))
    db.execute(text(CREATE_ESTADO_SQL))
    db.commit()

    now = datetime.utcnow()

    cat_count = db.execute(text("SELECT COUNT(*) FROM ActivoCategoria")).scalar()
    if cat_count == 0:
        for nombre, grupo, montable in _SEED_CATEGORIAS:
            db.execute(text("""
                INSERT INTO ActivoCategoria (nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios, activo, createdAt, updatedAt)
                VALUES (:nombre, :grupo, :montable, 0, NULL, 1, :now, :now)
            """), {"nombre": nombre, "grupo": grupo, "montable": montable, "now": now})

    est_count = db.execute(text("SELECT COUNT(*) FROM ActivoEstado")).scalar()
    if est_count == 0:
        for i, (nombre, codigo) in enumerate(_SEED_ESTADOS):
            db.execute(text("""
                INSERT INTO ActivoEstado (nombre, codigo, orden, esCore, activo, createdAt, updatedAt)
                VALUES (:nombre, :codigo, :orden, 1, 1, :now, :now)
            """), {"nombre": nombre, "codigo": codigo, "orden": i, "now": now})

    db.commit()


def listar_categorias(db: Session, grupo: str | None = None) -> list[dict]:
    """Categorias activas, opcionalmente filtradas por grupo, ordenadas por grupo y nombre."""
    query = "SELECT id, nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios FROM ActivoCategoria WHERE activo = 1"
    params = {}
    if grupo:
        query += " AND grupo = :grupo"
        params["grupo"] = grupo
    query += " ORDER BY grupo, nombre"
    rows = db.execute(text(query), params).mappings().all()
    return [
        {
            "id": r["id"], "nombre": r["nombre"], "grupo": r["grupo"],
            "montableEnPC": bool(r["montableEnPC"]), "requiereSerie": bool(r["requiereSerie"]),
            "vidaUtilAnios": r["vidaUtilAnios"],
        }
        for r in rows
    ]


def listar_fabricantes(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre FROM ActivoFabricante WHERE activo = 1 ORDER BY nombre")).mappings().all()
    return [dict(r) for r in rows]


def listar_proveedores(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre, contacto FROM ActivoProveedor WHERE activo = 1 ORDER BY nombre")).mappings().all()
    return [dict(r) for r in rows]


def listar_estados(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre, codigo, orden, esCore FROM ActivoEstado WHERE activo = 1 ORDER BY orden, nombre")).mappings().all()
    return [
        {"id": r["id"], "nombre": r["nombre"], "codigo": r["codigo"], "orden": r["orden"], "esCore": bool(r["esCore"])}
        for r in rows
    ]


def estado_es_core(db: Session, estado_id: int) -> bool:
    r = db.execute(text("SELECT esCore FROM ActivoEstado WHERE id = :id"), {"id": estado_id}).mappings().first()
    return bool(r["esCore"]) if r else False
