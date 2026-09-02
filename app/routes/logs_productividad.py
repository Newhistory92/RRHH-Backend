"""
Administracion de que actividad del sistema de gestion cuenta como trabajo.

El score se calculaba sobre UsuarioAccesoLogs, que registra altas y bajas de
permisos y no trabajo de nadie. La actividad real esta en LogSistema, pero
cruda incluye login, refresh de token y polling, que no son trabajo. Estos
endpoints permiten decidir cual es cual.

Todo acceso a ObraSocial es SELECT. La configuracion se guarda en RRHH.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.database.rutas_productividad import (
    configuracion_actual,
    ensure_table,
    upsert_rutas,
)
from app.services.normalizar_ruta import normalizar_ruta

router = APIRouter(
    prefix="/admin/logs",
    tags=["Logs productividad"],
    dependencies=[Depends(require_permission("admin.gestionar"))],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_logs_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()


def armar_catalogo(
    agregado: list[dict],
    config: dict[tuple[str, str], float],
) -> list[dict]:
    """
    Cruza la actividad observada con la configuracion guardada.

    El agregado viene con URLs crudas, una fila por URL distinta; aca se las
    normaliza y se suman las que colapsan en la misma ruta. El cruce ocurre en
    Python y no en SQL porque las dos tablas viven en bases distintas, y la
    normalizacion tambien, para no tener la misma logica escrita dos veces en
    dos lenguajes.

    Funcion pura, sin I/O.
    """
    acumulado: dict[tuple[str, str], dict] = {}

    for fila in agregado:
        clave = (fila["metodo"], normalizar_ruta(fila["url"]))
        actual = acumulado.get(clave)
        if actual is None:
            acumulado[clave] = {
                "metodo": clave[0],
                "ruta": clave[1],
                "eventos": fila["eventos"],
                # Es el maximo por URL cruda y no el distinct real del grupo:
                # sumarlos contaria dos veces a quien uso varias URLs de la
                # misma ruta, y eso exageraria el alcance de la ruta.
                "usuarios": fila["usuarios"],
                "ultimaVez": fila["ultimaVez"],
            }
        else:
            actual["eventos"] += fila["eventos"]
            actual["usuarios"] = max(actual["usuarios"], fila["usuarios"])
            actual["ultimaVez"] = max(actual["ultimaVez"], fila["ultimaVez"])

    catalogo = []
    for clave, datos in acumulado.items():
        peso = config.get(clave)
        if peso is None:
            estado = "pendiente"
        elif peso > 0:
            estado = "cuenta"
        else:
            estado = "no_cuenta"
        catalogo.append({**datos, "estado": estado})

    catalogo.sort(key=lambda f: f["eventos"], reverse=True)
    return catalogo


AGREGADO_SQL = text("""
    SELECT
        metodo,
        url,
        COUNT(*) AS eventos,
        COUNT(DISTINCT idUsuario) AS usuarios,
        CONVERT(VARCHAR(10), MAX(fechaHoraLog), 23) AS ultimaVez
    FROM [ObraSocial].[dbo].[LogSistema]
    WHERE fechaHoraLog >= DATEADD(MONTH, -:meses, GETDATE())
      AND idUsuario IS NOT NULL
      AND statusCode >= 200 AND statusCode < 300
    GROUP BY metodo, url
""")


@router.get("/rutas")
def listar_rutas(
    meses: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    logs_db: Session = Depends(get_logs_db),
):
    """
    Catalogo de rutas observadas con su estado de clasificacion.

    Si ObraSocial no responde se devuelve la configuracion guardada sin
    volumen, en vez de un error: la clasificacion vive en RRHH y se puede
    seguir trabajando sin la otra base.
    """
    ensure_table(db)
    config = configuracion_actual(db)

    try:
        filas = logs_db.execute(
            AGREGADO_SQL, {"meses": meses}
        ).mappings().all()
        agregado = [dict(f) for f in filas]
        actividad_disponible = True
    except Exception:
        agregado = []
        actividad_disponible = False

    catalogo = armar_catalogo(agregado, config)

    # Las rutas ya clasificadas que no aparecieron en la ventana siguen siendo
    # parte de la configuracion y tienen que poder des-clasificarse.
    vistas = {(f["metodo"], f["ruta"]) for f in catalogo}
    for (metodo, ruta), peso in config.items():
        if (metodo, ruta) not in vistas:
            catalogo.append({
                "metodo": metodo,
                "ruta": ruta,
                "eventos": 0,
                "usuarios": 0,
                "ultimaVez": None,
                "estado": "cuenta" if peso > 0 else "no_cuenta",
            })

    return {
        "rutas": catalogo,
        "actividadDisponible": actividad_disponible,
        "pendientes": sum(1 for f in catalogo if f["estado"] == "pendiente"),
    }


class RutaClasificada(BaseModel):
    metodo: str
    ruta: str
    cuenta: bool


class ClasificacionRequest(BaseModel):
    rutas: list[RutaClasificada]


@router.put("/rutas")
def guardar_rutas(
    payload: ClasificacionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("admin.gestionar")),
):
    """
    Guarda una tanda de clasificaciones.

    Recibe el lote entero y no una ruta por request porque el flujo real es
    tildar veinte de una pasada. Queda registrado quien clasifico: esto mueve
    scores que se usan para decidir ascensos, y tiene que ser trazable.
    """
    ensure_table(db)
    guardadas = upsert_rutas(
        db,
        [f.model_dump() for f in payload.rutas],
        clasificado_por=user.get("employeeId"),
    )
    return {"success": True, "guardadas": guardadas}


# Clases de status expuestas en el filtro. El mapa es cerrado a proposito: el
# valor llega del cliente y no puede convertirse en SQL arbitrario.
CLASES_STATUS = {
    "exito": "statusCode >= 200 AND statusCode < 300",
    "redireccion": "statusCode >= 300 AND statusCode < 400",
    "error_cliente": "statusCode >= 400 AND statusCode < 500",
    "error_servidor": "statusCode >= 500",
}


def construir_filtros(filtros: dict) -> tuple[str, dict]:
    """
    Arma el fragmento WHERE del explorador y sus binds.

    Todo valor del cliente viaja como bind, nunca interpolado. La clase de
    status es la unica que se traduce a SQL, y sale de un mapa cerrado.

    Funcion pura, sin I/O.
    """
    condiciones: list[str] = []
    binds: dict = {}

    if filtros.get("metodo"):
        condiciones.append("metodo = :metodo")
        binds["metodo"] = filtros["metodo"]

    if filtros.get("usuario"):
        condiciones.append("nombreUsuario = :usuario")
        binds["usuario"] = filtros["usuario"]

    if filtros.get("texto"):
        condiciones.append("url LIKE :texto")
        binds["texto"] = f"%{filtros['texto']}%"

    if filtros.get("desde"):
        condiciones.append("fechaHoraLog >= :desde")
        binds["desde"] = filtros["desde"]

    if filtros.get("hasta"):
        condiciones.append("fechaHoraLog < DATEADD(DAY, 1, :hasta)")
        binds["hasta"] = filtros["hasta"]

    clase = CLASES_STATUS.get(filtros.get("clase") or "")
    if clase:
        condiciones.append(f"({clase})")

    return (" AND ".join(condiciones), binds)


@router.get("")
def listar_logs(
    metodo: str | None = None,
    usuario: str | None = None,
    texto: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    clase: str | None = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=200),
    logs_db: Session = Depends(get_logs_db),
):
    """
    Explorador de logs crudos, paginado.

    Devuelve las columnas tal como estan, sin normalizar: el objetivo es
    entender que paso realmente antes de decidir si una ruta cuenta.
    """
    where, binds = construir_filtros({
        "metodo": metodo, "usuario": usuario, "texto": texto,
        "desde": desde, "hasta": hasta, "clase": clase,
    })
    clausula = f"WHERE {where}" if where else ""

    total = logs_db.execute(
        text(f"SELECT COUNT(*) AS n FROM [ObraSocial].[dbo].[LogSistema] {clausula}"),
        binds,
    ).mappings().first()

    filas = logs_db.execute(
        text(f"""
            SELECT fechaHoraLog, nombreUsuario, metodo, url,
                   statusCode, tiempoRespuestaMs, requestId
            FROM [ObraSocial].[dbo].[LogSistema]
            {clausula}
            ORDER BY fechaHoraLog DESC
            OFFSET :salto ROWS FETCH NEXT :toma ROWS ONLY
        """),
        {**binds,
         "salto": max(0, (pagina - 1) * por_pagina),
         "toma": por_pagina},
    ).mappings().all()

    # Se adjunta la ruta normalizada de cada fila para que la pantalla pueda
    # saltar de un log a clasificar su ruta. Se calcula aca y no en el cliente
    # para que exista una sola implementacion de la normalizacion: dos, en dos
    # lenguajes, se desincronizan y el salto llevaria a la ruta equivocada.
    return {
        "logs": [
            {**dict(f), "rutaNormalizada": normalizar_ruta(f["url"])}
            for f in filas
        ],
        "total": total["n"] if total else 0,
        "pagina": pagina,
        "porPagina": por_pagina,
    }


@router.post("/recalcular")
def recalcular_scores(
    db: Session = Depends(get_db),
    stats_db: Session = Depends(get_logs_db),
):
    """
    Dispara a mano la misma corrida que hace el scheduler cada dia.

    Existe porque tildar rutas no tiene efecto visible hasta la corrida
    siguiente, y esa demora se lee como que la pantalla no funciona. El
    recalculo alcanza los 12 meses de la ventana, no solo lo que viene: la
    clasificacion describe que es trabajo, y eso no depende de cuando se tildo.
    """
    from app.routes.stats import sync_productivity_scores

    try:
        sync_productivity_scores(db, stats_db)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo recalcular: {e}",
        )
    return {"success": True}
