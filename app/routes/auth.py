from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
from jose import jwt
import bcrypt
import os
from dotenv import load_dotenv
from app.database.database import SessionLocal
from app.database.token_blacklist import (
    add_to_blacklist,
    is_blacklisted,
    cleanup_expired,
    ensure_table,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración del router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/auth", tags=["Auth"])

# ---------------------------------------------------------------------------
# Configuración JWT — leída desde variables de entorno
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY no está configurada en el .env. "
        "Agrega JWT_SECRET_KEY=<clave_segura_larga> al archivo .env."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "2"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ---------------------------------------------------------------------------
# Dependencia DB
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Inicializar tabla de blacklist al cargar el módulo
# ---------------------------------------------------------------------------
def init_blacklist():
    """Crea la tabla TokenBlacklist si no existe. Llamar desde main.py al inicio."""
    db = SessionLocal()
    try:
        ensure_table(db)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 🔐 LOGIN — Autenticación de usuario
# ---------------------------------------------------------------------------
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = form_data.username
    password = form_data.password
    print(f"🔐 Intento de login para usuario: {usuario}")

    # Buscar usuario por nombre o email
    query = text("SELECT * FROM [User] WHERE usuario = :usuario OR email = :usuario")
    result = db.execute(query, {"usuario": usuario}).fetchone()

    if not result:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    user = dict(result._mapping)

    # Verificar si está activo
    if not user.get("activo", True):
        raise HTTPException(status_code=403, detail="Usuario inhabilitado")

    # Verificar contraseña
    if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    # Obtener información del rol
    query_role = text("SELECT name FROM Role WHERE id = :roleId")
    role_result = db.execute(query_role, {"roleId": user["roleId"]}).fetchone()
    role_name = role_result.name if role_result else "Desconocido"

    # Crear token JWT
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": user["usuario"], "roleId": user["roleId"], "exp": expire}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    print(f"✅ Usuario {user['usuario']} autenticado correctamente con rol: {role_name}")

    employee_id = user.get("employeeId")

    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": user["usuario"],
        "roleId": user["roleId"],
        "roleName": role_name,
        "employeeId": employee_id,
    }


# ---------------------------------------------------------------------------
# 👤 ENDPOINT protegido: obtener usuario actual
# ---------------------------------------------------------------------------
@router.get("/me")
def get_me(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        if is_blacklisted(db, token):
            raise HTTPException(status_code=401, detail="Token invalidado")

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        usuario = payload.get("sub")

        if not usuario:
            raise HTTPException(status_code=401, detail="Token inválido")

        query = text("""
            SELECT u.id as user_id, u.usuario, u.email, u.roleId, u.createdAt, u.employeeId,
                   e.name as employee_name, e.photo as employee_photo
            FROM [User] u
            LEFT JOIN Employee e ON u.employeeId = e.id
            WHERE u.usuario = :usuario
        """)
        result = db.execute(query, {"usuario": usuario}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        return dict(result._mapping)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido o expirado: {e}")


# ---------------------------------------------------------------------------
# 🚪 LOGOUT — Invalida el token en la blacklist persistente
# ---------------------------------------------------------------------------
@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Cierra sesión invalidando el token JWT en la base de datos."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # La expiración original del token
        exp_timestamp = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc).replace(tzinfo=None)
    except jwt.ExpiredSignatureError:
        # Si ya expiró, no hace falta blacklistearlo — igualmente respondemos 200
        print("🚪 Logout de token ya expirado (no se agrega a blacklist)")
        return {"message": "Sesión cerrada correctamente"}
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    # Agregar a la blacklist persistente
    add_to_blacklist(db, token, expires_at)

    # Limpiar tokens viejos en cada logout (mantenimiento automático)
    removed = cleanup_expired(db)
    print(f"🚪 Token invalidado. Tokens expirados eliminados: {removed}")

    return {"message": "Sesión cerrada correctamente"}


# ---------------------------------------------------------------------------
# ✅ VERIFY — Valida token (llamado desde el middleware de Next.js)
# ---------------------------------------------------------------------------
@router.post("/verify")
async def verify_token_route(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")

    token = auth_header.split(" ")[1]

    # Limpiar tokens expirados de la blacklist periódicamente
    cleanup_expired(db)

    # Verificar si fue revocado explícitamente
    if is_blacklisted(db, token):
        raise HTTPException(status_code=401, detail="Token invalidado")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"valid": True, "usuario": payload["sub"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
