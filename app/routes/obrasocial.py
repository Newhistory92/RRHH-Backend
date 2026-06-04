from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocalObraSocial

router = APIRouter(prefix="/obrasocial", tags=["ObraSocial"])

def get_obrasocial_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()

@router.get("/usuarios")
def get_usuarios_acceso(db: Session = Depends(get_obrasocial_db)):
    """
    Obtiene todos los usuarios de [ObraSocial].[dbo].[UsuarioAcceso]
    Esta base de datos es independiente de la base de datos de 'paginaprueba' donde se encuentra la tabla [User].
    """
    try:
        query = text("SELECT * FROM [ObraSocial].[dbo].[UsuarioAcceso]")
        result = db.execute(query).fetchall()
        usuarios = [dict(row._mapping) for row in result]
        return {"usuarios": usuarios}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con la base de datos ObraSocial: {str(e)}")
