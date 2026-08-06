import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.cors_config import setup_cors
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes, asistencia, asistencia_ausencias
from app.routes.auth import init_blacklist
from app.scheduler import iniciar_scheduler, detener_scheduler
from app.database.database import SessionLocal
from app.database.marcaciones import ensure_columna_biometrico
from app.database.asistencia import ensure_tables as ensure_tablas_asistencia

app = FastAPI(title="Backend RRHH", version="1.0")

setup_cors(app)

# Carpeta de adjuntos del Portal Institucional (subsistema 3): se sirve
# estaticamente y se crea al importar si no existe.
os.makedirs("uploads/publications", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Inicializar tabla TokenBlacklist en DB al arrancar
@app.on_event("startup")
def startup():
    print("[*] Iniciando app...")
    init_blacklist()
    print("[OK] init_blacklist ejecutado")
    db = SessionLocal()
    try:
        ensure_columna_biometrico(db)
        print("[OK] columna biometricoId verificada")
        ensure_tablas_asistencia(db)
        print("[OK] tablas de asistencia verificadas")
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

@app.get("/")
def root():
    return {"message": "Bienvenido a la API RRHH"}


# python -m uvicorn app.main:app --reload
# .\venv\Scripts\Activate