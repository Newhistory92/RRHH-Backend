import os
import sys

# La consola de Windows usa cp1252, que no sabe codificar los emoji que hay
# repartidos en los print() de los routers (auth, licenses, employee, etc.).
# Sin esto, un print con un emoji levanta UnicodeEncodeError y tumba el
# request -- o el arranque. Con errors="replace" el emoji sale como "?" y el
# servidor sigue andando.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.cors_config import setup_cors
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes, asistencia, asistencia_ausencias, chat
from app.routes.auth import init_blacklist
from app.scheduler import iniciar_scheduler, detener_scheduler
from app.database.database import SessionLocal
from app.database.marcaciones import ensure_columna_biometrico
from app.database.asistencia import ensure_tables as ensure_tablas_asistencia
from app.database.provisioning import ensure_columna_origen
from app.database.permissions import ensure_tables as ensure_permission_tables, sembrar
from app.database.score_exencion import ensure_columnas_exencion

app = FastAPI(title="Backend RRHH", version="1.0")

setup_cors(app)

# Carpeta de adjuntos del Portal Institucional (subsistema 3): se sirve
# estaticamente y se crea al importar si no existe.
os.makedirs("uploads/publications", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def init_permisos():
    """Crea las tablas de permisos y siembra la asignacion inicial."""
    db = SessionLocal()
    try:
        ensure_permission_tables(db)
        roles = sembrar(db)
        print(f"[OK] Permisos sembrados. Roles: {roles}")
    finally:
        db.close()


# Inicializar tabla TokenBlacklist en DB al arrancar
@app.on_event("startup")
def startup():
    print("[*] Iniciando app...")
    init_blacklist()
    print("[OK] init_blacklist ejecutado")
    init_permisos()
    print("[OK] init_permisos ejecutado")
    db = SessionLocal()
    try:
        ensure_columna_biometrico(db)
        print("[OK] columna biometricoId verificada")
        ensure_tablas_asistencia(db)
        print("[OK] tablas de asistencia verificadas")
        from sqlalchemy import text as _text
        db.execute(_text(
            "IF COL_LENGTH('Message','category') IS NULL "
            "ALTER TABLE Message ADD category NVARCHAR(20) NULL"
        ))
        db.commit()
        print("[OK] columna Message.category verificada")
        db.execute(_text(
            "IF COL_LENGTH('Message','leida') IS NULL "
            "ALTER TABLE Message ADD leida BIT NOT NULL DEFAULT 0"
        ))
        db.commit()
        print("[OK] columna Message.leida verificada")
        ensure_columna_origen(db)
        print("[OK] columna origen de [User] verificada")
        ensure_columnas_exencion(db)
        print("[OK] columnas scoreExento verificadas")
    finally:
        db.close()
    iniciar_scheduler()
    print("[OK] scheduler de relojes iniciado")


@app.on_event("shutdown")
def shutdown():
    detener_scheduler()

# Registrar los routers
app.include_router(employee.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(role.router)
app.include_router(rrhh.router)
app.include_router(active.router)
app.include_router(departments.router)
app.include_router(tests.router)
app.include_router(feedback.router)
app.include_router(licenses.router)
app.include_router(obrasocial.router)
app.include_router(stats.router)
app.include_router(configtest.router)
app.include_router(contracts.router)
app.include_router(professions.router)
app.include_router(schedules.router)
app.include_router(reubicacion.router)
app.include_router(publications.router)
app.include_router(activos_config.router)
app.include_router(activos_modelos.router)
app.include_router(activos.router)
app.include_router(relojes.router)
app.include_router(asistencia.router)
app.include_router(asistencia_ausencias.router)
app.include_router(chat.router)

@app.get("/")
def root():
    return {"message": "Bienvenido a la API RRHH"}


# .\venv\Scripts\Activate
#
# Desarrollo (solo esta maquina):
#   python -m uvicorn app.main:app --reload
#
# Servidor / red institucional -- OBLIGATORIO --host 0.0.0.0:
#   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
#
# Sin --host 0.0.0.0 uvicorn escucha solo en 127.0.0.1 y ninguna otra PC de
# la red puede conectarse (ERR_CONNECTION_REFUSED en el navegador del cliente).
# Ademas hay que habilitar el puerto 8000 en el Firewall de Windows del server.