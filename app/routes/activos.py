"""
Router /activos -- CRUD del inventario (subsistema 2). Lecturas: cualquier
autenticado. Escrituras: solo ADMIN. Cada mutacion escribe en ActivoHistorial
dentro de la misma transaccion.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
)

router = APIRouter(prefix="/activos", tags=["Activos"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return value[:10]  # 'YYYY-MM-DD' -- SQL Server DATE lo acepta bindeado
    return value


_RESPONSABLE_TABLA = {"empleado": "Employee", "oficina": "Office", "departamento": "Department"}


def _validar_responsable(db: Session, data: dict) -> dict:
    """Devuelve dict con tipo + los 3 ids (los no aplicables en None). 400 si es inconsistente
    o si el id referenciado no existe en la tabla del organigrama correspondiente."""
    tipo = data.get("responsableTipo")
    if tipo is None or tipo == "":
        return {"tipo": None, "empleado": None, "oficina": None, "departamento": None}
    if tipo not in RESPONSABLE_TIPOS:
        raise HTTPException(status_code=400, detail=f"responsableTipo debe ser uno de: {sorted(RESPONSABLE_TIPOS)}")
    ids = {
        "empleado": data.get("responsableEmpleadoId") if tipo == "empleado" else None,
        "oficina": data.get("responsableOficinaId") if tipo == "oficina" else None,
        "departamento": data.get("responsableDepartamentoId") if tipo == "departamento" else None,
    }
    if not ids[tipo]:
        raise HTTPException(status_code=400, detail=f"Falta el id del responsable para el tipo '{tipo}'")
    tabla = _RESPONSABLE_TABLA[tipo]  # tipo ya validado contra RESPONSABLE_TIPOS: nombre de tabla fijo, no interpolacion de entrada de usuario
    existe = db.execute(text(f"SELECT id FROM {tabla} WHERE id = :id"), {"id": ids[tipo]}).first()
    if not existe:
        raise HTTPException(status_code=400, detail=f"El {tipo} responsable indicado no existe")
    return {"tipo": tipo, **ids}


def _resolver_estado(db: Session, estado_id: Optional[int]) -> int:
    if estado_id:
        r = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": estado_id}).first()
        if not r:
            raise HTTPException(status_code=400, detail="estadoId inexistente")
        return estado_id
    default_id = estado_disponible_id(db)
    if not default_id:
        raise HTTPException(status_code=400, detail="No existe el estado 'Disponible'; verifique la configuracion")
    return default_id


def _validar_comunes(db: Session, data: dict) -> tuple:
    """Valida obligatorios/FK/serie. Devuelve (nombre, categoria, requiereSerie)."""
    numero = (data.get("numeroInventario") or "").strip()
    if not numero:
        raise HTTPException(status_code=400, detail="El numero de inventario es obligatorio")
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if not data.get("fechaAlta"):
        raise HTTPException(status_code=400, detail="La fecha de alta es obligatoria")
    cat = db.execute(text("SELECT id, requiereSerie FROM ActivoCategoria WHERE id = :id AND activo = 1"),
                     {"id": data.get("categoriaId")}).mappings().first()
    if not cat:
        raise HTTPException(status_code=400, detail="categoriaId inexistente")
    if data.get("fabricanteId"):
        fab = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"),
                         {"id": data.get("fabricanteId")}).first()
        if not fab:
            raise HTTPException(status_code=400, detail="fabricanteId inexistente")
    if cat["requiereSerie"] and not (data.get("numeroSerie") or "").strip():
        raise HTTPException(status_code=400, detail="Esta categoria requiere numero de serie")
    return numero, cat["id"], bool(cat["requiereSerie"])


# ─── Lectura ─────────────────────────────────────────────────────────────────
@router.get("", dependencies=[Depends(require_any_auth)])
def get_activos(categoriaId: Optional[int] = None, grupo: Optional[str] = None,
                estadoId: Optional[int] = None, texto: Optional[str] = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"activos": listar_activos(db, categoriaId, grupo, estadoId, texto)}


@router.get("/buscar", dependencies=[Depends(require_any_auth)])
def get_por_codigo(codigo: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = buscar_por_codigo(db, codigo)
    if not activo:
        raise HTTPException(status_code=404, detail="No se encontro un activo con ese codigo")
    return activo


@router.get("/{activo_id}", dependencies=[Depends(require_any_auth)])
def get_activo(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = obtener_activo(db, activo_id)
    if not activo:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return activo


# ─── Escritura ───────────────────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_admin)])
def crear_activo(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    numero, cat_id, _ = _validar_comunes(db, data)
    dup = db.execute(text("SELECT id FROM Activo WHERE activo = 1 AND numeroInventario = :n"), {"n": numero}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe un activo con ese numero de inventario")
    estado_id = _resolver_estado(db, data.get("estadoId"))
    resp = _validar_responsable(db, data)
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO Activo (numeroInventario, nombre, categoriaId, fabricanteId, estadoId, fechaAlta, anio,
            observaciones, imagenReferencial, numeroSerie, codigoBarras, codigoQR,
            responsableTipo, responsableEmpleadoId, responsableOficinaId, responsableDepartamentoId,
            activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:numero, :nombre, :catId, :fabId, :estId, :fechaAlta, :anio,
            :obs, :img, :serie, :barras, :qr,
            :rtipo, :remp, :rofi, :rdep, 1, :now, :now)
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "now": now,
    })
    new_id = result.scalar()
    registrar_historial(db, new_id, "creacion", None, None, numero, current_user.get("employeeId"))
    db.commit()
    return {"id": new_id}


@router.put("/{activo_id}", dependencies=[Depends(require_admin)])
def actualizar_activo(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    numero, cat_id, _ = _validar_comunes(db, data)
    dup = db.execute(text("SELECT id FROM Activo WHERE activo = 1 AND numeroInventario = :n AND id <> :id"),
                     {"n": numero, "id": activo_id}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe un activo con ese numero de inventario")
    estado_id = _resolver_estado(db, data.get("estadoId"))
    resp = _validar_responsable(db, data)
    usuario = current_user.get("employeeId")

    # Historial de cambios relevantes
    if estado_id != actual["estadoId"]:
        nuevo_est = db.execute(text("SELECT nombre FROM ActivoEstado WHERE id = :id"), {"id": estado_id}).mappings().first()
        registrar_historial(db, activo_id, "cambio_estado", "estado", actual["estadoNombre"],
                            nuevo_est["nombre"] if nuevo_est else str(estado_id), usuario)
    resp_cambio = (resp["tipo"] != actual["responsableTipo"] or
                   resp["empleado"] != actual["responsableEmpleadoId"] or
                   resp["oficina"] != actual["responsableOficinaId"] or
                   resp["departamento"] != actual["responsableDepartamentoId"])
    if resp_cambio:
        registrar_historial(db, activo_id, "cambio_responsable", "responsable",
                            actual["responsableNombre"], _nombre_responsable(db, resp), usuario)
    otros_cambio = (numero != actual["numeroInventario"] or (data.get("nombre") or "").strip() != actual["nombre"]
                    or cat_id != actual["categoriaId"])
    if otros_cambio:
        registrar_historial(db, activo_id, "modificacion", "datos", None, None, usuario)

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE Activo SET numeroInventario = :numero, nombre = :nombre, categoriaId = :catId,
            fabricanteId = :fabId, estadoId = :estId, fechaAlta = :fechaAlta, anio = :anio,
            observaciones = :obs, imagenReferencial = :img, numeroSerie = :serie,
            codigoBarras = :barras, codigoQR = :qr, responsableTipo = :rtipo,
            responsableEmpleadoId = :remp, responsableOficinaId = :rofi, responsableDepartamentoId = :rdep,
            updatedAt = :now
        WHERE id = :id
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "now": now, "id": activo_id,
    })
    db.commit()
    return {"message": "Activo actualizado"}


@router.patch("/{activo_id}/estado", dependencies=[Depends(require_admin)])
def cambiar_estado(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                   current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    nuevo_id = data.get("estadoId")
    nuevo = db.execute(text("SELECT id, nombre FROM ActivoEstado WHERE id = :id AND activo = 1"),
                       {"id": nuevo_id}).mappings().first()
    if not nuevo:
        raise HTTPException(status_code=400, detail="estadoId inexistente")
    if nuevo["id"] != actual["estadoId"]:
        registrar_historial(db, activo_id, "cambio_estado", "estado", actual["estadoNombre"], nuevo["nombre"],
                            current_user.get("employeeId"), (data.get("observacion") or None))
    db.execute(text("UPDATE Activo SET estadoId = :est, updatedAt = :now WHERE id = :id"),
               {"est": nuevo["id"], "now": datetime.utcnow(), "id": activo_id})
    db.commit()
    return {"message": "Estado actualizado"}


@router.delete("/{activo_id}", dependencies=[Depends(require_admin)])
def baja_activo(activo_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    registrar_historial(db, activo_id, "baja", None, actual["numeroInventario"], None, current_user.get("employeeId"))
    db.execute(text("UPDATE Activo SET activo = 0, updatedAt = :now WHERE id = :id"),
               {"now": datetime.utcnow(), "id": activo_id})
    db.commit()
    return {"message": "Activo dado de baja"}


def _nombre_responsable(db: Session, resp: dict) -> Optional[str]:
    """Resuelve el nombre legible del nuevo responsable para el historial."""
    if resp["tipo"] == "empleado" and resp["empleado"]:
        r = db.execute(text("SELECT name AS n FROM Employee WHERE id = :id"), {"id": resp["empleado"]}).mappings().first()
        return r["n"] if r else None
    if resp["tipo"] == "oficina" and resp["oficina"]:
        r = db.execute(text("SELECT nombre AS n FROM Office WHERE id = :id"), {"id": resp["oficina"]}).mappings().first()
        return r["n"] if r else None
    if resp["tipo"] == "departamento" and resp["departamento"]:
        r = db.execute(text("SELECT nombre AS n FROM Department WHERE id = :id"), {"id": resp["departamento"]}).mappings().first()
        return r["n"] if r else None
    return None
