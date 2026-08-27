"""
Dobles compartidos por los tests de autenticacion.

FakeSession imita lo justo de sqlalchemy.orm.Session para el codigo que usa
text() con binds nombrados: se le da un diccionario que mapea un fragmento
distintivo del SQL a las filas que debe devolver.
"""

import bcrypt


def hash_bcrypt(texto: str) -> str:
    """Hash bcrypt real, para que checkpw se ejerza de verdad en los tests."""
    return bcrypt.hashpw(texto.encode(), bcrypt.gensalt()).decode()


class FakeResult:
    def __init__(self, filas: list[dict]):
        self._filas = filas

    def mappings(self):
        return self

    def first(self):
        return self._filas[0] if self._filas else None

    def all(self):
        return list(self._filas)

    def fetchone(self):
        return self._filas[0] if self._filas else None

    @property
    def rowcount(self):
        """len(filas) del fragmento que matcheo. Sirve para UPDATE/DELETE
        que en produccion devuelven cuantas filas afecto la sentencia."""
        return len(self._filas)

    def scalar(self):
        if not self._filas:
            return None
        primera = self._filas[0]
        return next(iter(primera.values())) if isinstance(primera, dict) else primera


class FakeSession:
    """
    respuestas: {fragmento_sql: [filas]}. La primera clave que aparezca como
    substring del SQL ejecutado gana. Si ninguna coincide devuelve vacio.

    ejecutadas guarda (sql, params) de cada llamada para poder afirmar sobre
    lo que el codigo intento hacer.
    """

    def __init__(self, respuestas: dict | None = None):
        self.respuestas = respuestas or {}
        self.ejecutadas: list[tuple[str, dict | None]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.ejecutadas.append((sql, params))
        for fragmento, filas in self.respuestas.items():
            if fragmento in sql:
                return FakeResult(filas)
        return FakeResult([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def sql_ejecutado(self) -> str:
        """Todo el SQL concatenado. Util para afirmar que algo NO se ejecuto."""
        return "\n".join(sql for sql, _ in self.ejecutadas)
