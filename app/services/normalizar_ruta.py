"""
Normalizacion de URLs crudas a rutas canonicas.

LogSistema guarda la URL tal cual llego, con el id del recurso adentro y el
query string pegado. Eso da 8.514 combinaciones distintas de metodo+URL, que
es imposible de clasificar a mano. Colapsando los identificadores quedan
1.830, y las 25 primeras concentran el 79% del volumen.

Funcion pura, sin I/O: es la unidad que decide que es "la misma ruta" para
toda la aplicacion, asi que tiene que ser testeable sin base.
"""

import re

# Un GUID canonico. Se ancla a los extremos para no matchear un segmento que
# apenas contenga algo con esa forma.
GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _es_identificador(segmento: str) -> bool:
    """
    Un segmento es identificador si es todo digitos o un GUID.

    Deliberadamente NO se colapsa cualquier cosa que contenga numeros: 'v2' y
    'covid19' son nombres de recurso y colapsarlos fusionaria rutas distintas
    en una sola fila del catalogo.
    """
    return segmento.isdigit() or bool(GUID.match(segmento))


def normalizar_ruta(url: str | None) -> str:
    """
    Devuelve la ruta canonica de una URL cruda.

    Descarta el query string y reemplaza por ':id' los segmentos que son
    identificadores, de modo que /orden/123 y /orden/456 sean la misma ruta.
    """
    if not url:
        return "/"

    sin_query = url.split("?", 1)[0]
    if not sin_query:
        return "/"

    partes = [
        ":id" if _es_identificador(p) else p
        for p in sin_query.split("/")
    ]
    return "/".join(partes) or "/"
