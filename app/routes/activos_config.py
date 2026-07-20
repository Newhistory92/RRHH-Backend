"""
Router /activos/config -- CRUD de la configuracion del Sistema de Activos
(subsistema 1). Lecturas: cualquier autenticado (selectores). Escrituras:
solo ADMIN.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN
from app.database.activos_config import (
    ensure_tables, VALID_GRUPOS,
    listar_categorias, listar_fabricantes, listar_proveedores, listar_estados,
    estado_es_core,
)

router = APIRouter(prefix="/activos/config", tags=["Activos Config"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _nombre_valido(data: dict) -> str:
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    return nombre


# ─── Categorias ──────────────────────────────────────────────────────────────
@router.get("/categorias", dependencies=[Depends(require_any_auth)])
def get_categorias(grupo: Optional[str] = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"categorias": listar_categorias(db, grupo)}


@router.post("/categorias", dependencies=[Depends(require_admin)])
def crear_categoria(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    grupo = data.get("grupo")
    if grupo not in VALID_GRUPOS:
        raise HTTPException(status_code=400, detail=f"grupo debe ser uno de: {sorted(VALID_GRUPOS)}")
    dup = db.execute(text("""
        SELECT id FROM ActivoCategoria WHERE activo = 1 AND grupo = :grupo AND LOWER(nombre) = LOWER(:nombre)
    """), {"grupo": grupo, "nombre": nombre}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe una categoria con ese nombre en el grupo")
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoCategoria (nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :grupo, :montable, :serie, :vida, 1, :now, :now)
    """), {
        "nombre": nombre, "grupo": grupo,
        "montable": 1 if data.get("montableEnPC") else 0,
        "serie": 1 if data.get("requiereSerie") else 0,
        "vida": data.get("vidaUtilAnios"),
        "now": now,
    })
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/categorias/{cat_id}", dependencies=[Depends(require_admin)])
def actualizar_categoria(cat_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    grupo = data.get("grupo")
    if grupo not in VALID_GRUPOS:
        raise HTTPException(status_code=400, detail=f"grupo debe ser uno de: {sorted(VALID_GRUPOS)}")
    existing = db.execute(text("SELECT id FROM ActivoCategoria WHERE id = :id AND activo = 1"), {"id": cat_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    dup = db.execute(text("""
        SELECT id FROM ActivoCategoria WHERE activo = 1 AND grupo = :grupo AND LOWER(nombre) = LOWER(:nombre) AND id <> :id
    """), {"grupo": grupo, "nombre": nombre, "id": cat_id}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe una categoria con ese nombre en el grupo")
    db.execute(text("""
        UPDATE ActivoCategoria SET nombre = :nombre, grupo = :grupo, montableEnPC = :montable,
            requiereSerie = :serie, vidaUtilAnios = :vida, updatedAt = :now WHERE id = :id
    """), {
        "nombre": nombre, "grupo": grupo,
        "montable": 1 if data.get("montableEnPC") else 0,
        "serie": 1 if data.get("requiereSerie") else 0,
        "vida": data.get("vidaUtilAnios"),
        "now": datetime.utcnow(), "id": cat_id,
    })
    db.commit()
    return {"message": "Categoria actualizada"}


@router.delete("/categorias/{cat_id}", dependencies=[Depends(require_admin)])
def baja_categoria(cat_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoCategoria WHERE id = :id AND activo = 1"), {"id": cat_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    db.execute(text("UPDATE ActivoCategoria SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": cat_id})
    db.commit()
    return {"message": "Categoria eliminada"}


# ─── Fabricantes ─────────────────────────────────────────────────────────────
@router.get("/fabricantes", dependencies=[Depends(require_any_auth)])
def get_fabricantes(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"fabricantes": listar_fabricantes(db)}


@router.post("/fabricantes", dependencies=[Depends(require_admin)])
def crear_fabricante(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoFabricante (nombre, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, 1, :now, :now)
    """), {"nombre": nombre, "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/fabricantes/{fab_id}", dependencies=[Depends(require_admin)])
def actualizar_fabricante(fab_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    existing = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"), {"id": fab_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Fabricante no encontrado")
    db.execute(text("UPDATE ActivoFabricante SET nombre = :nombre, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "now": datetime.utcnow(), "id": fab_id})
    db.commit()
    return {"message": "Fabricante actualizado"}


@router.delete("/fabricantes/{fab_id}", dependencies=[Depends(require_admin)])
def baja_fabricante(fab_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"), {"id": fab_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Fabricante no encontrado")
    db.execute(text("UPDATE ActivoFabricante SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": fab_id})
    db.commit()
    return {"message": "Fabricante eliminado"}


# ─── Proveedores ─────────────────────────────────────────────────────────────
@router.get("/proveedores", dependencies=[Depends(require_any_auth)])
def get_proveedores(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"proveedores": listar_proveedores(db)}


@router.post("/proveedores", dependencies=[Depends(require_admin)])
def crear_proveedor(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoProveedor (nombre, contacto, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, :contacto, 1, :now, :now)
    """), {"nombre": nombre, "contacto": data.get("contacto"), "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/proveedores/{prov_id}", dependencies=[Depends(require_admin)])
def actualizar_proveedor(prov_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    existing = db.execute(text("SELECT id FROM ActivoProveedor WHERE id = :id AND activo = 1"), {"id": prov_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.execute(text("UPDATE ActivoProveedor SET nombre = :nombre, contacto = :contacto, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "contacto": data.get("contacto"), "now": datetime.utcnow(), "id": prov_id})
    db.commit()
    return {"message": "Proveedor actualizado"}


@router.delete("/proveedores/{prov_id}", dependencies=[Depends(require_admin)])
def baja_proveedor(prov_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoProveedor WHERE id = :id AND activo = 1"), {"id": prov_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.execute(text("UPDATE ActivoProveedor SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": prov_id})
    db.commit()
    return {"message": "Proveedor eliminado"}


# ─── Estados ─────────────────────────────────────────────────────────────────
@router.get("/estados", dependencies=[Depends(require_any_auth)])
def get_estados(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"estados": listar_estados(db)}


@router.post("/estados", dependencies=[Depends(require_admin)])
def crear_estado(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    codigo = (data.get("codigo") or "").strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El codigo es obligatorio")
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoEstado (nombre, codigo, orden, esCore, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, :codigo, :orden, 0, 1, :now, :now)
    """), {"nombre": nombre, "codigo": codigo, "orden": data.get("orden") or 0, "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/estados/{est_id}", dependencies=[Depends(require_admin)])
def actualizar_estado(est_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    codigo = (data.get("codigo") or "").strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El codigo es obligatorio")
    existing = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": est_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    db.execute(text("UPDATE ActivoEstado SET nombre = :nombre, codigo = :codigo, orden = :orden, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "codigo": codigo, "orden": data.get("orden") or 0, "now": datetime.utcnow(), "id": est_id})
    db.commit()
    return {"message": "Estado actualizado"}


@router.delete("/estados/{est_id}", dependencies=[Depends(require_admin)])
def baja_estado(est_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": est_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    if estado_es_core(db, est_id):
        raise HTTPException(status_code=400, detail="Los estados nucleo no se pueden eliminar")
    db.execute(text("UPDATE ActivoEstado SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": est_id})
    db.commit()
    return {"message": "Estado eliminado"}
