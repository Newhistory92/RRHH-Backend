from app.database.database import SessionLocal
from sqlalchemy import text

def check_columns():
    db = SessionLocal()
    try:
        # Check standard columns in ConfiguracionLicencias
        print("Checking ConfiguracionLicencias columns...")
        result = db.execute(text("SELECT TOP 1 * FROM ConfiguracionLicencias")).mappings().first()
        if result:
            print(f"Columns: {result.keys()}")
        else:
            print("Table is empty, checking schema via information_schema...")
            cols = db.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'ConfiguracionLicencias'")).fetchall()
            print(f"Columns in INFORMATION_SCHEMA: {[c[0] for c in cols]}")

        print("\nChecking CondicionLaboral columns...")
        result_cl = db.execute(text("SELECT TOP 1 * FROM CondicionLaboral")).mappings().first()
        if result_cl:
            print(f"Columns: {result_cl.keys()}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_columns()
