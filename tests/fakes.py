"""
Fakes para tests: FakeSession mapea fragmentos de SQL a filas.

Un query matches un key si el key aparece en el SQL string.
"""


class FakeResult:
    """Resultado simulado de una query."""

    def __init__(self, filas: list[dict]):
        self.filas = filas

    def mappings(self):
        """Retorna self para poder encadenar .all()."""
        return self

    def all(self):
        """Retorna la lista de dicts."""
        return self.filas

    def first(self):
        """Retorna el primer dict o None."""
        return self.filas[0] if self.filas else None


class FakeSession:
    """Mock de sesion SQLAlchemy que mapea fragmentos SQL a resultados."""

    def __init__(self, mapa: dict[str, list[dict]]):
        """
        mapa: dict que mapea fragmentos de SQL (que aparecen en la query)
              a listas de dicts que simular ser los resultados.
        """
        self.mapa = mapa
        self.ejecutadas: list[tuple[str, dict]] = []

    def execute(self, sql_text, params=None):
        """Ejecuta una query contra el mapa, registrando la ejecucion."""
        if params is None:
            params = {}

        # sql_text puede ser un objeto text() de SQLAlchemy con un atributo text
        sql_str = str(sql_text)
        if hasattr(sql_text, 'text'):
            sql_str = sql_text.text

        self.ejecutadas.append((sql_str, params))

        # Encuentra el primer key del mapa que aparece en el SQL
        for key, filas in self.mapa.items():
            if key in sql_str:
                return FakeResult(filas)

        # Si no encontro nada, retorna resultado vacio
        return FakeResult([])

    def commit(self):
        """No-op: no hay nada que commitear en una fake."""
        pass

    def rollback(self):
        """No-op: no hay nada que rollbackear."""
        pass
