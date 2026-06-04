from sqlalchemy import text
from app.database.database import SessionLocal
from datetime import date

def debug_saldos(employee_id):
    db = SessionLocal()
    try:
        print(f"Checking for employee_id: {employee_id}")
        cl = db.execute(text("SELECT tipoContrato, fechaIngreso FROM CondicionLaboral WHERE employeeId = :id"), {"id": employee_id}).mappings().first()
        if not cl:
            print("Employee not found in CondicionLaboral")
            return
        
        tipo_contrato = cl["tipoContrato"]
        print(f"Found tipoContrato: {tipo_contrato}")
        
        # Test the Seeder logic
        anio = 2024 # Example
        print(f"Testing seeder for year {anio}")
        
        # Test if tipoContrato column exists in ConfiguracionLicencias
        try:
            db.execute(text("SELECT TOP 1 tipoContrato FROM ConfiguracionLicencias"))
            print("Column 'tipoContrato' exists in ConfiguracionLicencias")
        except Exception as e:
            print(f"Column 'tipoContrato' does NOT exist in ConfiguracionLicencias: {e}")
            
        # Test the 3-year bag select
        try:
            query = text("""
                SELECT c.anio, c.tipo, c.diasTotales
                FROM ConfiguracionLicencias c
                WHERE c.tipoContrato = :contrato
            """)
            result = db.execute(query, {"contrato": tipo_contrato}).mappings().fetchall()
            print(f"Query successful, found {len(result)} records")
        except Exception as e:
            print(f"Query failed: {e}")
            
    finally:
        db.close()

if __name__ == "__main__":
    debug_saldos(8)
