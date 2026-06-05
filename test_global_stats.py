import sys
import os

# Agregamos la ruta base para que pueda importar módulos locales
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.database import SessionLocal
from app.routes.stats import get_global_stats

def test():
    db = SessionLocal()
    try:
        result = get_global_stats(db)
        print("Success:", result["success"])
        import pprint
        pprint.pprint(result["data"])
    except Exception as e:
        print("Error:", e)
    finally:
        db.close()

if __name__ == "__main__":
    test()
