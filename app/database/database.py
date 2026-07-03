from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
OBRASOCIAL_DATABASE_URL = os.getenv("OBRASOCIAL_DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

engine_obrasocial = create_engine(OBRASOCIAL_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocalObraSocial = sessionmaker(autocommit=False, autoflush=False, bind=engine_obrasocial)

# --- DEBUG: Probar conexión a ObraSocial al arrancar ---
print("[*] Configurando conexion a ObraSocial...")
try:
    # Mostramos la URL sin el password para verificar el host/db
    safe_url = OBRASOCIAL_DATABASE_URL.split("@")[-1]
    print(f"[+] URL (host/db): {safe_url}")

    with engine_obrasocial.connect() as conn:
        print("[OK] Conexion exitosa a la base de datos ObraSocial.")
except Exception as e:
    print(f"[ERROR] Conexion critica a ObraSocial: {e}")
# -------------------------------------------------------
