"""
Que rutas del sistema de gestion cuentan como trabajo para el score.

Vive en la base de RRHH y no en ObraSocial: esa base es de solo lectura sin
excepcion, y ademas la decision de que cuenta es de RRHH, no del sistema que
genera los logs.

La columna es un decimal y no un bit aunque la interfaz de esta etapa sea un
checkbox. El dia que se quiera decir que crear una internacion vale 3 y buscar
vale 1, es cambiar la UI: ni migracion de datos ni reescritura del calculo.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('RutaProductividad', 'U') IS NULL
CREATE TABLE RutaProductividad (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    metodo         NVARCHAR(10)  NOT NULL,
    ruta           NVARCHAR(500) NOT NULL,
    peso           DECIMAL(5,2)  NOT NULL DEFAULT 0,
    clasificadoPor INT           NULL,
    clasificadoEn  DATETIME2     NULL,
    notas          NVARCHAR(500) NULL,
    CONSTRAINT UQ_RutaProductividad_metodo_ruta UNIQUE (metodo, ruta)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def configuracion_actual(db: Session) -> dict[tuple[str, str], float]:
    """
    Toda la configuracion guardada, indexada por (metodo, ruta).

    Que una ruta NO aparezca aca significa "pendiente de clasificar", que es
    un estado distinto de "clasificada en cero": las dos no suman al score,
    pero solo la primera tiene que aparecerle al administrador como novedad.
    """
    filas = db.execute(text("""
        SELECT metodo, ruta, peso
        FROM RutaProductividad
    """)).mappings().all()
    return {(f["metodo"], f["ruta"]): float(f["peso"]) for f in filas}


def rutas_habilitadas(db: Session) -> set[tuple[str, str]]:
    """Las rutas que suman al score. Es lo que consume el calculo."""
    return {
        clave for clave, peso in configuracion_actual(db).items() if peso > 0
    }


def upsert_rutas(
    db: Session,
    filas: list[dict],
    clasificado_por: int | None,
) -> int:
    """
    Guarda una tanda de clasificaciones.

    Cada fila es {"metodo", "ruta", "cuenta"}. El booleano se traduce a peso
    1 o 0; la API expone el booleano porque la interfaz de esta etapa es
    binaria, y la tabla guarda el decimal para no atarse a eso.

    Es MERGE y no INSERT porque reclasificar una ruta ya vista es el caso
    normal, y la clave (metodo, ruta) es unica.
    """
    if not filas:
        return 0

    db.execute(
        text("""
            MERGE RutaProductividad AS destino
            USING (SELECT :metodo AS metodo, :ruta AS ruta) AS origen
                ON destino.metodo = origen.metodo AND destino.ruta = origen.ruta
            WHEN MATCHED THEN
                UPDATE SET peso = :peso,
                           clasificadoPor = :clasificadoPor,
                           clasificadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (metodo, ruta, peso, clasificadoPor, clasificadoEn)
                VALUES (:metodo, :ruta, :peso, :clasificadoPor, GETDATE());
        """),
        [
            {
                "metodo": f["metodo"],
                "ruta": f["ruta"],
                "peso": 1 if f.get("cuenta") else 0,
                "clasificadoPor": clasificado_por,
            }
            for f in filas
        ],
    )
    db.commit()
    return len(filas)
