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


def ensure_tables(db: Session) -> None:
    """Crea Activo y ActivoHistorial si no existen (idempotente)."""
    db.execute(text(CREATE_ACTIVO_SQL))
    db.execute(text(CREATE_HISTORIAL_SQL))
    db.commit()


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
        END AS responsableNombre
    FROM Activo a
    INNER JOIN ActivoCategoria c ON a.categoriaId = c.id
    INNER JOIN ActivoEstado e    ON a.estadoId = e.id
    LEFT  JOIN ActivoFabricante f ON a.fabricanteId = f.id
    LEFT  JOIN Employee re   ON a.responsableEmpleadoId = re.id
    LEFT  JOIN Office ro     ON a.responsableOficinaId = ro.id
    LEFT  JOIN Department rd ON a.responsableDepartamentoId = rd.id
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
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
    }


def listar_activos(db: Session, categoria_id: Optional[int] = None, grupo: Optional[str] = None,
                   estado_id: Optional[int] = None, texto: Optional[str] = None) -> list[dict]:
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
