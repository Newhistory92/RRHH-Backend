# test_connection.py

#.\venv\Scripts\Activate


from app.database.database import engine

try:
    with engine.connect() as connection:
        print("✅ Conexión exitosa a SQL Server")
except Exception as e:
    print("❌ Error al conectar:", e)

