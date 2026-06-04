import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
try:
    from app.database.database import SessionLocalObraSocial
    from sqlalchemy import text
    db = SessionLocalObraSocial()
    res = db.execute(text("SELECT TOP 1 * FROM [ObraSocial].[dbo].[UsuarioAccesoLogs]"))
    print("LOG_COLUMNS:" + ",".join(res.keys()))
    db.close()
except Exception as e:
    print(f"ERROR: {str(e)}")
