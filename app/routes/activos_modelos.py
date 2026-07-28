"""
Router /activos/modelos -- modelos de PC de referencia y scoring (subsistema 6).
Lecturas: cualquier autenticado. Escrituras: solo ADMIN.
Se registra ANTES que activos.router en main.py para que /activos/modelos/... no
sea capturado por el path converter /{activo_id} de aquel.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN
from app.database.activos_modelos import (
    ensure_tables, CAMPOS_SPEC_POR_CATEGORIA, campos_disponibles,
    listar_modelos, obtener_modelo, crear_modelo, actualizar_modelo, baja_modelo,
    nombre_duplicado, agregar_requisito, requisito_duplicado, quitar_requisito,
    evaluar_pc,
)

router = APIRouter(prefix="/activos/modelos", tags=["Activos - Modelos"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_nombre(data: dict) -> str:
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    return nombre


@router.get("", dependencies=[Depends(require_any_auth)])
def get_modelos(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"modelos": listar_modelos(db)}


@router.get("/campos", dependencies=[Depends(require_any_auth)])
def get_campos(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"categorias": campos_disponibles(db)}


@router.get("/evaluar/{pc_id}", dependencies=[Depends(require_any_auth)])
def get_evaluacion(pc_id: int, modeloId: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    pc = db.execute(text("""
        SELECT a.id, c.puedeAlbergarComponentes
        FROM Activo a
        INNER JOIN ActivoCategoria c ON a.categoriaId = c.id
        WHERE a.id = :id AND a.activo = 1
    """), {"id": pc_id}).mappings().first()
    if not pc:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    if not pc["puedeAlbergarComponentes"]:
        raise HTTPException(status_code=400, detail="Este activo no es una PC")
    if not obtener_modelo(db, modeloId):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return evaluar_pc(db, pc_id, modeloId)


@router.get("/{modelo_id}", dependencies=[Depends(require_any_auth)])
def get_modelo(modelo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    modelo = obtener_modelo(db, modelo_id)
    if not modelo:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return modelo


@router.post("", dependencies=[Depends(require_admin)])
def post_modelo(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _validar_nombre(data)
    if nombre_duplicado(db, nombre):
        raise HTTPException(status_code=400, detail="Ya existe un modelo con ese nombre")
    new_id = crear_modelo(db, nombre, data.get("descripcion") or None)
    db.commit()
    return {"id": new_id}


@router.put("/{modelo_id}", dependencies=[Depends(require_admin)])
def put_modelo(modelo_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    nombre = _validar_nombre(data)
    if nombre_duplicado(db, nombre, excluir_id=modelo_id):
        raise HTTPException(status_code=400, detail="Ya existe un modelo con ese nombre")
    actualizar_modelo(db, modelo_id, nombre, data.get("descripcion") or None)
    db.commit()
    return {"message": "Modelo actualizado"}


@router.delete("/{modelo_id}", dependencies=[Depends(require_admin)])
def delete_modelo(modelo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    baja_modelo(db, modelo_id)
    db.commit()
    return {"message": "Modelo dado de baja"}


@router.post("/{modelo_id}/requisitos", dependencies=[Depends(require_admin)])
def post_requisito(modelo_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")

    categoria_id = data.get("categoriaId")
    cat = db.execute(text(
        "SELECT id, nombre, montableEnPC FROM ActivoCategoria WHERE id = :id AND activo = 1"
    ), {"id": categoria_id}).mappings().first() if categoria_id else None
    if not cat:
        raise HTTPException(status_code=400, detail="categoriaId inexistente")
    if not cat["montableEnPC"]:
        raise HTTPException(status_code=400, detail="La categoria debe ser montable en una PC")

    campo = (data.get("campoSpec") or "").strip()
    validos = [c["campo"] for c in CAMPOS_SPEC_POR_CATEGORIA.get(cat["nombre"], [])]
    if campo not in validos:
        raise HTTPException(status_code=400,
                            detail=f"campoSpec invalido para {cat['nombre']}. Validos: {validos}")

    try:
        valor = float(data.get("valorMinimo"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="valorMinimo debe ser numerico")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="valorMinimo debe ser mayor a 0")

    if requisito_duplicado(db, modelo_id, cat["id"], campo):
        raise HTTPException(status_code=400, detail="Ya existe un requisito para esa categoria y campo")

    new_id = agregar_requisito(db, modelo_id, cat["id"], campo, valor)
    db.commit()
    return {"id": new_id}


@router.delete("/{modelo_id}/requisitos/{requisito_id}", dependencies=[Depends(require_admin)])
def delete_requisito(modelo_id: int, requisito_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not quitar_requisito(db, modelo_id, requisito_id):
        raise HTTPException(status_code=404, detail="Requisito no encontrado en ese modelo")
    db.commit()
    return {"message": "Requisito eliminado"}
