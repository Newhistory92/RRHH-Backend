from fastapi import FastAPI
from app.cors_config import setup_cors
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats
from app.routes.auth import init_blacklist

app = FastAPI(title="Backend RRHH", version="1.0")

setup_cors(app)

# Inicializar tabla TokenBlacklist en DB al arrancar
@app.on_event("startup")
def startup():
    print("🚀 Iniciando app...")
    init_blacklist()
    print("✅ init_blacklist ejecutado")

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

@app.get("/")
def root():
    return {"message": "Bienvenido a la API RRHH 🚀"}


# python -m uvicorn app.main:app --reload
# .\venv\Scripts\Activate