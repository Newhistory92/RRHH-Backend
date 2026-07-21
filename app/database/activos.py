"""
Activos del Sistema de Gestion de Activos (subsistema 2). Entidad principal
Activo (inventario) + ActivoHistorial (auditoria inmutable, se escribe en cada
mutacion). Consume la config de S1 (ActivoCategoria/ActivoFabricante/ActivoEstado)
y el organigrama existente (Employee/Office/Department).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional


RESPONSABLE_TIPOS = {"empleado", "oficina", "departamento"}


# Mapeo de nombre de ActivoCategoria (S1) -> category del catalogo PCParts (dataset).
# Las categorias sin entrada aqui simplemente no ofrecen autocompletado.
MAPEO_PCPARTS = {
    "CPU": "cpu",
    "Memoria RAM": "memory",
    "Placas Base": "motherboard",
    "Tarjetas de Video": "video-card",
    "Almacenamiento": "internal-hard-drive",
    "Fuentes de Alimentación": "power-supply",
    "Disipadores CPU": "cpu-cooler",
    "Gabinetes": "case",
    "Unidades Ópticas": "optical-drive",
    "Tarjetas de Sonido": "sound-card",
    "Sistemas Operativos": "os",
    "Adaptadores de Red Cableados": "wired-network-card",
    "Adaptadores de Red Inalámbricos": "wireless-network-card",
    "Monitor": "monitor",
    "Almacenamiento Externo": "external-hard-drive",
    "UPS": "ups",
}


CREATE_ACTIVO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'Activo' AND xtype = 'U')
BEGIN
    CREATE TABLE Activo (
        id                        INT IDENTITY(1,1) PRIMARY KEY,
        numeroInventario          NVARCHAR(100)  NOT NULL,
        nombre                    NVARCHAR(300)  NOT NULL,
        categoriaId               INT            NOT NULL,
        fabricanteId              INT            NULL,
        estadoId                  INT            NOT NULL,
        fechaAlta                 DATE           NOT NULL,
        anio                      INT            NULL,
        observaciones             NVARCHAR(MAX)  NULL,
        imagenReferencial         NVARCHAR(1000) NULL,
        numeroSerie               NVARCHAR(200)  NULL,
        codigoBarras              NVARCHAR(200)  NULL,
        codigoQR                  NVARCHAR(500)  NULL,
        responsableTipo           NVARCHAR(20)   NULL,
        responsableEmpleadoId     INT            NULL,
        responsableOficinaId      INT            NULL,
        responsableDepartamentoId INT            NULL,
        activo                    BIT            NOT NULL DEFAULT 1,
        createdAt                 DATETIME2      NOT NULL,
        updatedAt                 DATETIME2      NOT NULL
    );
    CREATE INDEX IX_Activo_numeroInventario ON Activo (numeroInventario);
END
"""

CREATE_HISTORIAL_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoHistorial' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoHistorial (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        activoId          INT           NOT NULL,
        accion            NVARCHAR(30)  NOT NULL,
        campo             NVARCHAR(50)  NULL,
        valorAnterior     NVARCHAR(MAX) NULL,
        valorNuevo        NVARCHAR(MAX) NULL,
        usuarioEmpleadoId INT           NULL,
        observacion       NVARCHAR(500) NULL,
        createdAt         DATETIME2     NOT NULL
    );
    CREATE INDEX IX_ActivoHistorial_activoId ON ActivoHistorial (activoId);
END
"""


def ensure_columns(db: Session) -> None:
    """Agrega pcPadreId a Activo y puedeAlbergarComponentes a ActivoCategoria
    (idempotente), y marca la categoria 'PC' con el flag. El ALTER y el UPDATE
    van en batches separados: SQL Server compila el batch completo antes de
    ejecutarlo y fallaria con 'Invalid column name' si el UPDATE referenciara
    la columna recien creada en el mismo batch."""
    db.execute(text("IF COL_LENGTH('Activo','pcPadreId') IS NULL ALTER TABLE Activo ADD pcPadreId INT NULL;"))
    db.execute(text("IF COL_LENGTH('ActivoCategoria','puedeAlbergarComponentes') IS NULL "
                    "ALTER TABLE ActivoCategoria ADD puedeAlbergarComponentes BIT NOT NULL DEFAULT 0;"))
    db.commit()
    db.execute(text("UPDATE ActivoCategoria SET puedeAlbergarComponentes = 1 "
                    "WHERE nombre = 'PC' AND puedeAlbergarComponentes = 0;"))
    db.commit()


def ensure_tables(db: Session) -> None:
    """Crea Activo y ActivoHistorial si no existen (idempotente) y asegura las
    columnas de composicion (S3), asi todo endpoint que ya llamaba ensure_tables
    obtiene tambien las columnas nuevas antes de usar _SELECT_ACTIVO."""
    db.execute(text(CREATE_ACTIVO_SQL))
    db.execute(text(CREATE_HISTORIAL_SQL))
    db.commit()
    ensure_columns(db)


def registrar_historial(db: Session, activo_id: int, accion: str, campo: Optional[str],
                        valor_anterior: Optional[str], valor_nuevo: Optional[str],
                        usuario_id: Optional[int], observacion: Optional[str] = None) -> None:
    """Inserta una fila de historial. NO commitea -- corre dentro de la
    transaccion de la mutacion que lo llama."""
    db.execute(text("""
        INSERT INTO ActivoHistorial (activoId, accion, campo, valorAnterior, valorNuevo, usuarioEmpleadoId, observacion, createdAt)
        VALUES (:activoId, :accion, :campo, :valorAnterior, :valorNuevo, :usuarioId, :observacion, :now)
    """), {
        "activoId": activo_id, "accion": accion, "campo": campo,
        "valorAnterior": valor_anterior, "valorNuevo": valor_nuevo,
        "usuarioId": usuario_id, "observacion": observacion, "now": datetime.utcnow(),
    })


def estado_disponible_id(db: Session) -> Optional[int]:
    """Id del estado 'Disponible' (codigo='disponible'), para el default al crear."""
    r = db.execute(text("SELECT id FROM ActivoEstado WHERE codigo = 'disponible' AND activo = 1")).mappings().first()
    return r["id"] if r else None


# Fragmento de SELECT reutilizado por listado y detalle: resuelve nombres.
_SELECT_ACTIVO = """
    SELECT
        a.id, a.numeroInventario, a.nombre, a.categoriaId, a.fabricanteId, a.estadoId,
        a.fechaAlta, a.anio, a.observaciones, a.imagenReferencial, a.numeroSerie,
        a.codigoBarras, a.codigoQR, a.responsableTipo, a.responsableEmpleadoId,
        a.responsableOficinaId, a.responsableDepartamentoId, a.createdAt, a.updatedAt,
        c.nombre AS categoriaNombre, c.grupo AS grupo, c.requiereSerie AS requiereSerie,
        e.nombre AS estadoNombre, e.codigo AS estadoCodigo,
        f.nombre AS fabricanteNombre,
        CASE a.responsableTipo
            WHEN 'empleado'     THEN re.name
            WHEN 'oficina'      THEN ro.nombre
            WHEN 'departamento' THEN rd.nombre
            ELSE NULL
        END AS responsableNombre,
        CASE a.responsableTipo
            WHEN 'empleado'     THEN re.departmentId
            WHEN 'oficina'      THEN ro.departmentId
            WHEN 'departamento' THEN a.responsableDepartamentoId
            ELSE NULL
        END AS efectivoDepartamentoId,
        CASE a.responsableTipo
            WHEN 'empleado'     THEN reDept.nombre
            WHEN 'oficina'      THEN roDept.nombre
            WHEN 'departamento' THEN rd.nombre
            ELSE NULL
        END AS efectivoDepartamentoNombre,
        CASE a.responsableTipo
            WHEN 'empleado' THEN re.officeId
            WHEN 'oficina'  THEN a.responsableOficinaId
            ELSE NULL
        END AS efectivoOficinaId,
        CASE a.responsableTipo
            WHEN 'empleado' THEN reOffice.nombre
            WHEN 'oficina'  THEN ro.nombre
            ELSE NULL
        END AS efectivoOficinaNombre,
        a.pcPadreId,
        pcp.nombre AS pcPadreNombre,
        c.puedeAlbergarComponentes AS puedeAlbergarComponentes
    FROM Activo a
    INNER JOIN ActivoCategoria c ON a.categoriaId = c.id
    INNER JOIN ActivoEstado e    ON a.estadoId = e.id
    LEFT  JOIN ActivoFabricante f ON a.fabricanteId = f.id
    LEFT  JOIN Employee re     ON a.responsableEmpleadoId = re.id
    LEFT  JOIN Office ro       ON a.responsableOficinaId = ro.id
    LEFT  JOIN Department rd   ON a.responsableDepartamentoId = rd.id
    LEFT  JOIN Department reDept ON re.departmentId = reDept.id
    LEFT  JOIN Department roDept ON ro.departmentId = roDept.id
    LEFT  JOIN Office reOffice   ON re.officeId = reOffice.id
    LEFT  JOIN Activo pcp        ON a.pcPadreId = pcp.id
    WHERE a.activo = 1
"""


def _fila_a_dict(r) -> dict:
    return {
        "id": r["id"], "numeroInventario": r["numeroInventario"], "nombre": r["nombre"],
        "categoriaId": r["categoriaId"], "categoriaNombre": r["categoriaNombre"], "grupo": r["grupo"],
        "requiereSerie": bool(r["requiereSerie"]),
        "fabricanteId": r["fabricanteId"], "fabricanteNombre": r["fabricanteNombre"],
        "estadoId": r["estadoId"], "estadoNombre": r["estadoNombre"], "estadoCodigo": r["estadoCodigo"],
        "fechaAlta": r["fechaAlta"].isoformat() if r["fechaAlta"] else None,
        "anio": r["anio"], "observaciones": r["observaciones"], "imagenReferencial": r["imagenReferencial"],
        "numeroSerie": r["numeroSerie"], "codigoBarras": r["codigoBarras"], "codigoQR": r["codigoQR"],
        "responsableTipo": r["responsableTipo"], "responsableNombre": r["responsableNombre"],
        "responsableEmpleadoId": r["responsableEmpleadoId"], "responsableOficinaId": r["responsableOficinaId"],
        "responsableDepartamentoId": r["responsableDepartamentoId"],
        "efectivoDepartamentoId": r["efectivoDepartamentoId"],
        "efectivoDepartamentoNombre": r["efectivoDepartamentoNombre"],
        "efectivoOficinaId": r["efectivoOficinaId"],
        "efectivoOficinaNombre": r["efectivoOficinaNombre"],
        "pcPadreId": r["pcPadreId"],
        "pcPadreNombre": r["pcPadreNombre"],
        "puedeAlbergarComponentes": bool(r["puedeAlbergarComponentes"]),
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
    }


def listar_activos(db: Session, categoria_id: Optional[int] = None, grupo: Optional[str] = None,
                   estado_id: Optional[int] = None, texto: Optional[str] = None,
                   departamento_id: Optional[int] = None, oficina_id: Optional[int] = None) -> list[dict]:
    """Activos vigentes con nombres resueltos, con filtros opcionales."""
    query = _SELECT_ACTIVO
    params = {}
    if categoria_id:
        query += " AND a.categoriaId = :catId"
        params["catId"] = categoria_id
    if grupo:
        query += " AND c.grupo = :grupo"
        params["grupo"] = grupo
    if estado_id:
        query += " AND a.estadoId = :estId"
        params["estId"] = estado_id
    if texto:
        query += " AND (a.nombre LIKE :q OR a.numeroInventario LIKE :q OR a.numeroSerie LIKE :q)"
        params["q"] = f"%{texto}%"
    if departamento_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado'     THEN re.departmentId
                WHEN 'oficina'      THEN ro.departmentId
                WHEN 'departamento' THEN a.responsableDepartamentoId
                ELSE NULL
            END) = :deptId"""
        params["deptId"] = departamento_id
    if oficina_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado' THEN re.officeId
                WHEN 'oficina'  THEN a.responsableOficinaId
                ELSE NULL
            END) = :ofiId"""
        params["ofiId"] = oficina_id
    query += " ORDER BY a.createdAt DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def obtener_activo(db: Session, activo_id: int) -> Optional[dict]:
    """Detalle de un activo vigente con nombres resueltos, o None."""
    r = db.execute(text(_SELECT_ACTIVO + " AND a.id = :id"), {"id": activo_id}).mappings().first()
    return _fila_a_dict(r) if r else None


def buscar_por_codigo(db: Session, codigo: str) -> Optional[dict]:
    """Busca un activo vigente cuyo numeroInventario/codigoBarras/codigoQR/numeroSerie
    coincida exactamente con el codigo dado."""
    r = db.execute(text(_SELECT_ACTIVO + """
        AND (a.numeroInventario = :cod OR a.codigoBarras = :cod OR a.codigoQR = :cod OR a.numeroSerie = :cod)
    """), {"cod": codigo}).mappings().first()
    return _fila_a_dict(r) if r else None


def listar_componentes_de(db: Session, pc_id: int) -> list[dict]:
    """Componentes vigentes instalados en la PC dada (pcPadreId = pc_id)."""
    rows = db.execute(text(_SELECT_ACTIVO + " AND a.pcPadreId = :pcId ORDER BY c.nombre, a.nombre"),
                      {"pcId": pc_id}).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def componentes_libres(db: Session, categoria_id: Optional[int] = None) -> list[dict]:
    """Activos vigentes montables en PC (categoria montableEnPC=1) que no estan
    instalados en ninguna PC (pcPadreId IS NULL). Filtro opcional por categoria."""
    query = _SELECT_ACTIVO + " AND a.pcPadreId IS NULL AND c.montableEnPC = 1"
    params = {}
    if categoria_id:
        query += " AND a.categoriaId = :catId"
        params["catId"] = categoria_id
    query += " ORDER BY c.nombre, a.nombre"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def buscar_pcparts(db: Session, pcparts_category: str, texto: str, limit: int = 20) -> list[dict]:
    """Filas del catalogo PCParts (solo lectura) filtradas por category exacta y
    texto opcional en el nombre. Siempre acotado por TOP."""
    rows = db.execute(text("""
        SELECT TOP (:limit) id, category, name, image, specs
        FROM PCParts
        WHERE category = :cat AND (:texto = '' OR name LIKE :q)
        ORDER BY name
    """), {"limit": limit, "cat": pcparts_category, "texto": texto, "q": f"%{texto}%"}).mappings().all()
    return [{"id": r["id"], "category": r["category"], "name": r["name"],
             "image": r["image"], "specs": r["specs"]} for r in rows]
