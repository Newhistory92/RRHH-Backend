# Autenticación institucional ObraSocial — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que los empleados de la institución entren al sistema RRHH con sus credenciales de ObraSocial, sin registrarse de nuevo, manteniendo una sola base de código que también sirve la versión comercial.

**Architecture:** Un proveedor de autenticación conmutable por la variable de entorno `AUTH_PROVIDER` decide contra qué se valida el login. El proveedor `local` reproduce el comportamiento actual; el proveedor `obrasocial` valida contra la base institucional y provisiona el `Employee` y el `[User]` en el primer login, vinculando por DNI. Un tab condicional en la pantalla Admin permite a RRHH importar usuarios proactivamente.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server vía pyodbc, bcrypt, pytest. Frontend Next.js con React y Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-04-auth-obrasocial-institucional-design.md`

**Rama:** `auth-obrasocial-institucional` (backend). El frontend trabaja sobre `main`.

## Global Constraints

- **No levantar servidor.** Ningún paso de este plan arranca uvicorn, `npm run dev` ni ningún proceso que escuche en un puerto. La verificación es por tests y por `tsc --noEmit`.
- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de solo lectura. No hay `INSERT`, `UPDATE` ni `DELETE` sobre esas tablas en ningún archivo.
- **Ningún test toca bases reales.** Los tests usan sesiones falsas definidas en `tests/fakes.py`.
- **Credenciales solo en `.env`.** `AUTH_PROVIDER`, `DATABASE_URL` y `OBRASOCIAL_DATABASE_URL` se leen con `os.getenv`. El `.env` no se commitea.
- **Valores exactos:** `AUTH_PROVIDER` acepta `local` (default) y `obrasocial`. `[User].origen` acepta `'local'` y `'obrasocial'`, `NVARCHAR(20) NOT NULL DEFAULT 'local'`. El rol asignado a los usuarios provisionados es `roleId = 2`. El dominio del email placeholder es `sin-email.local`.
- **Códigos HTTP exactos:** usuario inexistente → 401; contraseña incorrecta → 401; `anulado = True` → 403 con detalle `"Acceso denegado por la institución"`; DNI faltante → 400; DNI ya vinculado a otro `[User]` → 409.
- **SQL con binds nombrados.** Nunca interpolar valores en el string SQL. Las listas `IN (...)` se arman con binds generados (`:d0, :d1, …`), nunca con los valores directos.
- **Estilo del código:** comentarios y docstrings en castellano sin tildes (el resto del backend sigue esa convención por problemas de encoding). Los mensajes de error visibles al usuario sí llevan tildes.

---

## Estructura de archivos

**Backend — nuevos:**

| Archivo | Responsabilidad |
|---|---|
| `app/services/auth_providers/base.py` | Contrato `AuthProvider` y el dataclass `ResultadoAuth` |
| `app/services/auth_providers/mapeo.py` | Funciones puras `Persona` → campos de `Employee` |
| `app/services/auth_providers/local.py` | Proveedor por defecto: valida contra `[User]` |
| `app/services/auth_providers/obrasocial.py` | Proveedor institucional: tres caminos + `provisionar()` |
| `app/services/auth_providers/__init__.py` | `get_provider()` y `nombre_proveedor()` |
| `app/database/provisioning.py` | Escrituras y lecturas sobre la base RRHH para el alta automática |
| `app/database/obrasocial_usuarios.py` | Lecturas sobre la base institucional |
| `tests/fakes.py` | Sesión y resultado falsos, compartidos por los tests |

**Backend — modificados:**

| Archivo | Cambio |
|---|---|
| `app/routes/auth.py` | `/login` delega en el proveedor; nuevo `GET /auth/config` |
| `app/routes/obrasocial.py` | `GET /usuarios` enriquecido; nuevo `POST /importar` |
| `app/main.py` | Llama `ensure_columna_origen` en el startup |

**Frontend — nuevos:**

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/Admin/ObraSocialUsuariosTab.tsx` | Tabla de usuarios institucionales con selección e importación |

**Frontend — modificados:**

| Archivo | Cambio |
|---|---|
| `src/app/Interfas/Interfaces.ts` | Interface `UsuarioObraSocial` |
| `src/app/screens/Admin/Screen.tsx` | Tab condicional según `authProvider` |

---

### Task 1: Mapeo puro Persona → Employee

Traduce una fila de `ObraSocial.Persona` a los campos que `Employee` necesita. Es la única pieza sin dependencias: no toca base ni sesiones, así que se prueba directo.

**Files:**
- Create: `app/services/auth_providers/__init__.py` (vacío por ahora, Task 2 lo llena)
- Create: `app/services/auth_providers/mapeo.py`
- Test: `tests/test_auth_mapeo.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `DOMINIO_SIN_EMAIL: str` — la constante `"sin-email.local"`
  - `nombre_completo(persona: dict) -> str`
  - `placeholder_email(nombre_usuario: str) -> str`
  - `email_preferido(persona: dict, nombre_usuario: str) -> str`
  - `persona_a_employee(persona: dict, nombre_usuario: str) -> dict` — lanza `ValueError` si falta el DNI. Devuelve las claves `dni, name, email, gender, phone, birthDate, photo`.

- [ ] **Step 1: Crear el paquete vacío**

Crear `app/services/auth_providers/__init__.py` con este contenido exacto (Task 2 lo reemplaza):

```python
"""Proveedores de autenticacion conmutables por AUTH_PROVIDER."""
```

- [ ] **Step 2: Escribir los tests que fallan**

Crear `tests/test_auth_mapeo.py`:

```python
from datetime import datetime

import pytest

from app.services.auth_providers import mapeo


PERSONA_COMPLETA = {
    "nombrePersona": "Emiliano",
    "apellidoPersona": "Rojo",
    "numeroDocPersona": "35123456",
    "sexoPersona": "M",
    "telefonoPersona": "3794123456",
    "emailPersona": "erojo@institucion.gob.ar",
    "fechaNacPersona": datetime(1992, 5, 14),
    "fotoPersona": "data:image/png;base64,AAA",
}


# -- nombre_completo ----------------------------------------------------------

def test_nombre_completo_une_nombre_y_apellido():
    assert mapeo.nombre_completo(PERSONA_COMPLETA) == "Emiliano Rojo"


def test_nombre_completo_sin_apellido_no_deja_espacio_colgando():
    assert mapeo.nombre_completo({"nombrePersona": "Emiliano"}) == "Emiliano"


def test_nombre_completo_recorta_espacios_de_la_base():
    persona = {"nombrePersona": "  Emiliano  ", "apellidoPersona": " Rojo "}
    assert mapeo.nombre_completo(persona) == "Emiliano Rojo"


def test_nombre_completo_de_persona_vacia_es_cadena_vacia():
    assert mapeo.nombre_completo({}) == ""


# -- email --------------------------------------------------------------------

def test_email_preferido_usa_el_de_la_persona():
    assert mapeo.email_preferido(PERSONA_COMPLETA, "EmilianoRojo") == "erojo@institucion.gob.ar"


def test_email_preferido_cae_al_placeholder_si_esta_vacio():
    persona = {**PERSONA_COMPLETA, "emailPersona": "   "}
    assert mapeo.email_preferido(persona, "EmilianoRojo") == "EmilianoRojo@sin-email.local"


def test_email_preferido_cae_al_placeholder_si_es_nulo():
    persona = {**PERSONA_COMPLETA, "emailPersona": None}
    assert mapeo.email_preferido(persona, "EmilianoRojo") == "EmilianoRojo@sin-email.local"


def test_placeholder_usa_el_dominio_reservado():
    assert mapeo.placeholder_email("Juan") == f"Juan@{mapeo.DOMINIO_SIN_EMAIL}"


# -- persona_a_employee -------------------------------------------------------

def test_persona_a_employee_mapea_todos_los_campos():
    assert mapeo.persona_a_employee(PERSONA_COMPLETA, "EmilianoRojo") == {
        "dni": "35123456",
        "name": "Emiliano Rojo",
        "email": "erojo@institucion.gob.ar",
        "gender": "M",
        "phone": "3794123456",
        "birthDate": datetime(1992, 5, 14),
        "photo": "data:image/png;base64,AAA",
    }


def test_persona_a_employee_normaliza_el_dni_numerico():
    # La base institucional puede devolver el documento como int.
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": 35123456}
    assert mapeo.persona_a_employee(persona, "EmilianoRojo")["dni"] == "35123456"


def test_persona_a_employee_recorta_espacios_del_dni():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": " 35123456 "}
    assert mapeo.persona_a_employee(persona, "EmilianoRojo")["dni"] == "35123456"


def test_persona_sin_dni_no_se_puede_mapear():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": None}
    with pytest.raises(ValueError, match="documento"):
        mapeo.persona_a_employee(persona, "EmilianoRojo")


def test_persona_con_dni_vacio_no_se_puede_mapear():
    persona = {**PERSONA_COMPLETA, "numeroDocPersona": "   "}
    with pytest.raises(ValueError, match="documento"):
        mapeo.persona_a_employee(persona, "EmilianoRojo")
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_auth_mapeo.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.auth_providers.mapeo'`

- [ ] **Step 4: Escribir la implementación**

Crear `app/services/auth_providers/mapeo.py`:

```python
"""
Traduccion de una fila de ObraSocial.Persona a los campos que necesita
Employee. Son funciones puras: no tocan la base ni saben de sesiones, asi
que se prueban sin ningun doble.

La deteccion de email duplicado NO vive aca porque necesita consultar la
base. El llamador pregunta si el email preferido esta ocupado y, si lo esta,
usa placeholder_email.
"""

DOMINIO_SIN_EMAIL = "sin-email.local"


def nombre_completo(persona: dict) -> str:
    """Nombre y apellido unidos, sin espacios colgando si falta alguno."""
    nombre = (persona.get("nombrePersona") or "").strip()
    apellido = (persona.get("apellidoPersona") or "").strip()
    return " ".join(parte for parte in (nombre, apellido) if parte)


def placeholder_email(nombre_usuario: str) -> str:
    """
    Email de relleno cuando la persona no tiene uno o el suyo ya lo usa otro
    empleado. El dominio es reservado: no resuelve DNS, asi que ningun mail
    sale hacia afuera. Queda visible para que RRHH lo corrija.
    """
    return f"{nombre_usuario}@{DOMINIO_SIN_EMAIL}"


def email_preferido(persona: dict, nombre_usuario: str) -> str:
    email = (persona.get("emailPersona") or "").strip()
    return email or placeholder_email(nombre_usuario)


def persona_a_employee(persona: dict, nombre_usuario: str) -> dict:
    """
    Campos de Employee derivados de Persona.

    El DNI es obligatorio: es la clave que vincula los dos sistemas, y sin el
    no hay forma de encontrar ni de crear el empleado.
    """
    dni = str(persona.get("numeroDocPersona") or "").strip()
    if not dni:
        raise ValueError(
            "La persona no tiene numero de documento cargado en ObraSocial"
        )
    return {
        "dni": dni,
        "name": nombre_completo(persona),
        "email": email_preferido(persona, nombre_usuario),
        "gender": persona.get("sexoPersona"),
        "phone": persona.get("telefonoPersona"),
        "birthDate": persona.get("fechaNacPersona"),
        "photo": persona.get("fotoPersona"),
    }
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

```bash
py -m pytest tests/test_auth_mapeo.py -v
```

Esperado: PASS, 13 tests.

- [ ] **Step 6: Commit**

```bash
git add app/services/auth_providers/ tests/test_auth_mapeo.py
git commit -m "feat: mapeo puro de Persona (ObraSocial) a campos de Employee"
```

---

### Task 2: Proveedor conmutable y proveedor local

Introduce el contrato, el proveedor local que reproduce el comportamiento actual, y la selección por `.env`. Al terminar esta tarea el login funciona exactamente como antes — pero pasando por la nueva indirección.

**Files:**
- Create: `app/services/auth_providers/base.py`
- Create: `app/services/auth_providers/local.py`
- Create: `tests/fakes.py`
- Modify: `app/services/auth_providers/__init__.py` (reemplaza el stub de Task 1)
- Modify: `app/routes/auth.py:67-111` (la función `login`)
- Test: `tests/test_auth_provider_local.py`

**Interfaces:**
- Consumes: nada de Task 1.
- Produces:
  - `base.ResultadoAuth` — dataclass congelado con `usuario: str`, `roleId: int`, `employeeId: Optional[int]`
  - `base.AuthProvider` — Protocol con `autenticar(db: Session, usuario: str, password: str) -> ResultadoAuth`
  - `local.LocalAuthProvider` — implementa el protocolo
  - `nombre_proveedor() -> str` — el valor de `AUTH_PROVIDER` normalizado; lanza `RuntimeError` si es inválido
  - `get_provider() -> AuthProvider` — instancia el proveedor configurado
  - `fakes.FakeSession(respuestas: dict[str, list[dict]])` — sesión falsa; `respuestas` mapea un fragmento distintivo del SQL a las filas que devuelve
  - `fakes.hash_bcrypt(texto: str) -> str` — genera un hash bcrypt real para los tests

- [ ] **Step 1: Escribir el módulo de dobles**

Crear `tests/fakes.py`:

```python
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
```

- [ ] **Step 2: Escribir los tests que fallan**

Crear `tests/test_auth_provider_local.py`:

```python
import os

import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


HASH_SECRETO = hash_bcrypt("secreto")

USUARIO_ACTIVO = {
    "id": 7,
    "usuario": "erojo",
    "email": "erojo@rrhh.local",
    "password": HASH_SECRETO,
    "roleId": 1,
    "employeeId": 264,
    "activo": True,
    "origen": "local",
}


def _sesion(user_row=None):
    return FakeSession({"FROM [User]": [user_row] if user_row else []})


# -- LocalAuthProvider --------------------------------------------------------

def test_credenciales_validas_devuelven_el_resultado():
    from app.services.auth_providers.local import LocalAuthProvider

    resultado = LocalAuthProvider().autenticar(_sesion(USUARIO_ACTIVO), "erojo", "secreto")

    assert resultado.usuario == "erojo"
    assert resultado.roleId == 1
    assert resultado.employeeId == 264


def test_usuario_inexistente_da_401():
    from app.services.auth_providers.local import LocalAuthProvider

    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(None), "fantasma", "secreto")
    assert e.value.status_code == 401


def test_password_incorrecta_da_401():
    from app.services.auth_providers.local import LocalAuthProvider

    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(USUARIO_ACTIVO), "erojo", "otra")
    assert e.value.status_code == 401


def test_usuario_inhabilitado_da_403():
    from app.services.auth_providers.local import LocalAuthProvider

    inactivo = {**USUARIO_ACTIVO, "activo": False}
    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(inactivo), "erojo", "secreto")
    assert e.value.status_code == 403


def test_hash_corrupto_da_401_y_no_revienta():
    from app.services.auth_providers.local import LocalAuthProvider

    corrupto = {**USUARIO_ACTIVO, "password": "no-es-un-hash"}
    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(corrupto), "erojo", "secreto")
    assert e.value.status_code == 401


def test_empleado_sin_vincular_devuelve_employee_id_nulo():
    from app.services.auth_providers.local import LocalAuthProvider

    sin_empleado = {**USUARIO_ACTIVO, "employeeId": None}
    resultado = LocalAuthProvider().autenticar(_sesion(sin_empleado), "erojo", "secreto")
    assert resultado.employeeId is None


# -- Seleccion del proveedor --------------------------------------------------

def test_sin_variable_de_entorno_el_proveedor_es_local(monkeypatch):
    from app.services import auth_providers

    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    assert auth_providers.nombre_proveedor() == "local"


def test_el_valor_se_normaliza(monkeypatch):
    from app.services import auth_providers

    monkeypatch.setenv("AUTH_PROVIDER", "  LOCAL  ")
    assert auth_providers.nombre_proveedor() == "local"


def test_valor_invalido_falla_al_arrancar(monkeypatch):
    from app.services import auth_providers

    monkeypatch.setenv("AUTH_PROVIDER", "ldap")
    with pytest.raises(RuntimeError, match="AUTH_PROVIDER"):
        auth_providers.nombre_proveedor()


def test_get_provider_devuelve_la_instancia_local(monkeypatch):
    from app.services import auth_providers
    from app.services.auth_providers.local import LocalAuthProvider

    monkeypatch.setenv("AUTH_PROVIDER", "local")
    assert isinstance(auth_providers.get_provider(), LocalAuthProvider)
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_auth_provider_local.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.auth_providers.local'`

- [ ] **Step 4: Escribir el contrato**

Crear `app/services/auth_providers/base.py`:

```python
"""
Contrato de los proveedores de autenticacion.

El endpoint de login no sabe contra que se valida: pide el proveedor
configurado y le delega usuario y contrasena. Eso es lo que permite que la
version comercial y la institucional convivan en la misma base de codigo.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ResultadoAuth:
    """Lo minimo que el endpoint necesita para emitir el JWT."""

    usuario: str
    roleId: int
    employeeId: Optional[int]


class AuthProvider(Protocol):
    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        """
        Retorna el resultado si las credenciales son validas.

        Lanza HTTPException con el codigo que corresponda si no lo son: el
        proveedor decide el codigo porque conoce el motivo real del rechazo.
        """
        ...
```

- [ ] **Step 5: Escribir el proveedor local**

Crear `app/services/auth_providers/local.py`:

```python
"""
Proveedor por defecto: valida contra la tabla [User] de la propia base. Es el
comportamiento historico del sistema, movido detras del contrato sin cambios
de semantica.
"""

import bcrypt
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.auth_providers.base import ResultadoAuth


def verificar_password(plano: str, hash_almacenado: str) -> None:
    """
    Un hash corrupto o vacio en la base hace que bcrypt lance ValueError. Eso
    es una credencial invalida, no un error del servidor: se traduce a 401.
    """
    try:
        valida = bcrypt.checkpw(plano.encode(), (hash_almacenado or "").encode())
    except ValueError:
        valida = False
    if not valida:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")


class LocalAuthProvider:
    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        fila = db.execute(text("""
            SELECT usuario, password, roleId, employeeId, activo
            FROM [User]
            WHERE usuario = :u OR email = :u
        """), {"u": usuario}).mappings().first()

        if fila is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        if not fila["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")

        verificar_password(password, fila["password"])

        return ResultadoAuth(
            usuario=fila["usuario"],
            roleId=fila["roleId"],
            employeeId=fila["employeeId"],
        )
```

- [ ] **Step 6: Escribir la selección de proveedor**

Reemplazar el contenido completo de `app/services/auth_providers/__init__.py`:

```python
"""
Seleccion del proveedor de autenticacion segun AUTH_PROVIDER del .env.

    AUTH_PROVIDER=local        version comercial (default)
    AUTH_PROVIDER=obrasocial   version institucional

Una sola base de codigo cubre las dos variantes. No hay ramas divergentes:
cambiar de modo es cambiar una linea del .env.
"""

import os

from app.services.auth_providers.base import AuthProvider, ResultadoAuth
from app.services.auth_providers.local import LocalAuthProvider

PROVEEDOR_DEFAULT = "local"

# Task 4 agrega aca la entrada "obrasocial".
_PROVEEDORES = {
    "local": LocalAuthProvider,
}


def nombre_proveedor() -> str:
    """
    El valor configurado, normalizado. Un valor desconocido es un error de
    configuracion y tiene que explotar fuerte: caer silenciosamente al modo
    local dejaria una institucion entera sin su autenticacion real.
    """
    crudo = (os.getenv("AUTH_PROVIDER") or PROVEEDOR_DEFAULT).strip().lower()
    if crudo not in _PROVEEDORES:
        raise RuntimeError(
            f"AUTH_PROVIDER='{crudo}' no es un proveedor valido. "
            f"Opciones: {', '.join(sorted(_PROVEEDORES))}"
        )
    return crudo


def get_provider() -> AuthProvider:
    return _PROVEEDORES[nombre_proveedor()]()


__all__ = ["AuthProvider", "ResultadoAuth", "get_provider", "nombre_proveedor"]
```

- [ ] **Step 7: Correr los tests para verificar que pasan**

```bash
py -m pytest tests/test_auth_provider_local.py -v
```

Esperado: PASS, 10 tests.

- [ ] **Step 8: Conectar el endpoint de login al proveedor**

En `app/routes/auth.py`, agregar el import junto a los demás imports de `app`:

```python
from app.services.auth_providers import get_provider
```

Reemplazar la función `login` completa (desde `@router.post("/login")` hasta el `return` con `employee_id`) por:

```python
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    resultado = get_provider().autenticar(db, form_data.username, form_data.password)

    role_result = db.execute(
        text("SELECT name FROM Role WHERE id = :roleId"), {"roleId": resultado.roleId}
    ).fetchone()
    role_name = role_result.name if role_result else "Desconocido"

    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": resultado.usuario, "roleId": resultado.roleId, "exp": expire}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    print(f"✅ Usuario {resultado.usuario} autenticado correctamente con rol: {role_name}")

    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": resultado.usuario,
        "roleId": resultado.roleId,
        "roleName": role_name,
        "employeeId": resultado.employeeId,
    }
```

El import de `bcrypt` en `auth.py` queda sin uso: eliminarlo.

- [ ] **Step 9: Verificar que la suite completa sigue pasando**

```bash
py -m pytest tests/ -v
```

Esperado: PASS. Ningún test previo se rompe — el contrato del endpoint no cambió.

- [ ] **Step 10: Commit**

```bash
git add app/services/auth_providers/ app/routes/auth.py tests/fakes.py tests/test_auth_provider_local.py
git commit -m "feat: proveedor de autenticacion conmutable por AUTH_PROVIDER"
```

---

### Task 3: Capa de datos del provisioning

Todo lo que lee y escribe en la base RRHH durante el alta automática. Incluye la migración de la columna `origen`, que corre en el startup como el resto de las migraciones del proyecto.

**Files:**
- Create: `app/database/provisioning.py`
- Modify: `app/main.py:9-10` (imports) y `app/main.py:27-34` (bloque de startup)
- Test: `tests/test_provisioning.py`

**Interfaces:**
- Consumes: `tests.fakes.FakeSession` de Task 2.
- Produces:
  - `ROLE_USER: int = 2`, `ORIGEN_LOCAL: str = "local"`, `ORIGEN_OBRASOCIAL: str = "obrasocial"`
  - `ensure_columna_origen(db: Session) -> None`
  - `buscar_user(db: Session, usuario: str) -> Optional[dict]` — busca por `usuario` o `email`
  - `buscar_employee_por_dni(db: Session, dni: str) -> Optional[dict]`
  - `employees_por_dni(db: Session, dnis: list[str]) -> dict[str, int]`
  - `email_ocupado(db: Session, email: str) -> bool`
  - `user_de_employee(db: Session, employee_id: int) -> Optional[dict]`
  - `crear_employee(db: Session, datos: dict) -> int` — `datos` son las claves que produce `persona_a_employee`
  - `crear_user(db, usuario, email, password_hash, employee_id, origen, role_id=ROLE_USER) -> int`
  - `actualizar_password(db: Session, user_id: int, password_hash: str) -> None`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_provisioning.py`:

```python
from tests.fakes import FakeSession


DATOS_EMPLEADO = {
    "dni": "35123456",
    "name": "Emiliano Rojo",
    "email": "erojo@institucion.gob.ar",
    "gender": "M",
    "phone": "3794123456",
    "birthDate": None,
    "photo": None,
}


# -- Migracion ----------------------------------------------------------------

def test_ensure_columna_origen_es_idempotente():
    from app.database import provisioning as prov

    db = FakeSession()
    prov.ensure_columna_origen(db)

    sql = db.sql_ejecutado()
    assert "COL_LENGTH('[User]','origen')" in sql
    assert "NVARCHAR(20) NOT NULL DEFAULT 'local'" in sql
    assert db.commits == 1


# -- Lecturas -----------------------------------------------------------------

def test_buscar_user_encuentra_por_usuario_o_email():
    from app.database import provisioning as prov

    fila = {"id": 7, "usuario": "erojo", "origen": "local"}
    db = FakeSession({"FROM [User]": [fila]})

    assert prov.buscar_user(db, "erojo")["id"] == 7
    _, params = db.ejecutadas[0]
    assert params == {"u": "erojo"}


def test_buscar_user_inexistente_devuelve_none():
    from app.database import provisioning as prov

    assert prov.buscar_user(FakeSession(), "fantasma") is None


def test_buscar_employee_por_dni_devuelve_la_fila():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [{"id": 264, "dni": "35123456", "name": "Emiliano Rojo"}]})
    assert prov.buscar_employee_por_dni(db, "35123456")["id"] == 264


def test_employees_por_dni_arma_el_in_con_binds():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [
        {"id": 264, "dni": "35123456"},
        {"id": 265, "dni": " 40999888 "},
    ]})

    mapa = prov.employees_por_dni(db, ["35123456", "40999888", "11111111"])

    assert mapa == {"35123456": 264, "40999888": 265}
    sql, params = db.ejecutadas[0]
    assert ":d0, :d1, :d2" in sql
    assert params == {"d0": "35123456", "d1": "40999888", "d2": "11111111"}
    # Ningun valor interpolado en el SQL: solo binds.
    assert "35123456" not in sql


def test_employees_por_dni_con_lista_vacia_no_consulta():
    from app.database import provisioning as prov

    db = FakeSession()
    assert prov.employees_por_dni(db, []) == {}
    assert db.ejecutadas == []


def test_email_ocupado_es_true_si_hay_fila():
    from app.database import provisioning as prov

    db = FakeSession({"FROM Employee": [{"id": 1}]})
    assert prov.email_ocupado(db, "erojo@institucion.gob.ar") is True


def test_email_libre_es_false():
    from app.database import provisioning as prov

    assert prov.email_ocupado(FakeSession(), "nuevo@institucion.gob.ar") is False


def test_user_de_employee_devuelve_el_vinculado():
    from app.database import provisioning as prov

    db = FakeSession({"FROM [User]": [{"id": 7, "usuario": "erojo"}]})
    assert prov.user_de_employee(db, 264)["usuario"] == "erojo"


# -- Escrituras ---------------------------------------------------------------

def test_crear_employee_devuelve_el_id_y_commitea():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO Employee": [{"id": 300}]})
    assert prov.crear_employee(db, DATOS_EMPLEADO) == 300
    assert db.commits == 1


def test_crear_employee_pasa_todos_los_campos_del_mapeo():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO Employee": [{"id": 300}]})
    prov.crear_employee(db, DATOS_EMPLEADO)

    _, params = db.ejecutadas[0]
    for clave, valor in DATOS_EMPLEADO.items():
        assert params[clave] == valor
    assert "updatedAt" in params


def test_crear_user_usa_rol_user_por_defecto():
    from app.database import provisioning as prov

    db = FakeSession({"INSERT INTO [User]": [{"id": 9}]})
    nuevo = prov.crear_user(
        db, usuario="erojo", email="erojo@institucion.gob.ar",
        password_hash="$2b$10$hash", employee_id=300,
        origen=prov.ORIGEN_OBRASOCIAL,
    )

    assert nuevo == 9
    _, params = db.ejecutadas[0]
    assert params["roleId"] == prov.ROLE_USER == 2
    assert params["origen"] == "obrasocial"
    assert params["employeeId"] == 300
    assert db.commits == 1


def test_actualizar_password_escribe_el_hash_nuevo():
    from app.database import provisioning as prov

    db = FakeSession()
    prov.actualizar_password(db, 7, "$2b$10$nuevo")

    sql, params = db.ejecutadas[0]
    assert "UPDATE [User]" in sql
    assert params == {"p": "$2b$10$nuevo", "id": 7}
    assert db.commits == 1
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_provisioning.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.database.provisioning'`

- [ ] **Step 3: Escribir la implementación**

Crear `app/database/provisioning.py`:

```python
"""
Lecturas y escrituras sobre la base de RRHH necesarias para dar de alta
automaticamente a un usuario que viene de un sistema externo.

Este modulo no sabe nada de ObraSocial: recibe datos ya mapeados. Eso lo
deja reutilizable si algun dia se suma otra fuente de identidad.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

ROLE_USER = 2
ORIGEN_LOCAL = "local"
ORIGEN_OBRASOCIAL = "obrasocial"


def ensure_columna_origen(db: Session) -> None:
    """
    Marca de que sistema vino cada usuario.

    Sin esta columna un admin creado a mano en RRHH -- que no existe en la
    base externa -- quedaria bloqueado por la verificacion de bajas.
    """
    db.execute(text(
        "IF COL_LENGTH('[User]','origen') IS NULL "
        "ALTER TABLE [User] ADD origen NVARCHAR(20) NOT NULL DEFAULT 'local';"
    ))
    db.commit()


# -- Lecturas -----------------------------------------------------------------

def buscar_user(db: Session, usuario: str) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, usuario, email, password, roleId, employeeId, activo, origen
        FROM [User]
        WHERE usuario = :u OR email = :u
    """), {"u": usuario}).mappings().first()
    return dict(fila) if fila else None


def buscar_employee_por_dni(db: Session, dni: str) -> Optional[dict]:
    fila = db.execute(text(
        "SELECT id, dni, name FROM Employee WHERE dni = :dni"
    ), {"dni": dni}).mappings().first()
    return dict(fila) if fila else None


def employees_por_dni(db: Session, dnis: list[str]) -> dict[str, int]:
    """
    {dni: employeeId} para los DNIs que ya existen en RRHH. Una sola consulta
    para toda la lista: el tablero de importacion muestra cientos de filas.
    """
    if not dnis:
        return {}
    binds = {f"d{i}": valor for i, valor in enumerate(dnis)}
    marcadores = ", ".join(f":{clave}" for clave in binds)
    filas = db.execute(text(
        f"SELECT id, dni FROM Employee WHERE dni IN ({marcadores})"
    ), binds).mappings().all()
    return {str(f["dni"]).strip(): f["id"] for f in filas}


def email_ocupado(db: Session, email: str) -> bool:
    fila = db.execute(text(
        "SELECT id FROM Employee WHERE email = :email"
    ), {"email": email}).mappings().first()
    return fila is not None


def user_de_employee(db: Session, employee_id: int) -> Optional[dict]:
    """El [User] ya vinculado a ese empleado, si existe."""
    fila = db.execute(text(
        "SELECT id, usuario FROM [User] WHERE employeeId = :id"
    ), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None


# -- Escrituras ---------------------------------------------------------------

def crear_employee(db: Session, datos: dict) -> int:
    """
    Alta minima: solo los datos que la fuente externa conoce. Departamento,
    oficina, puesto y horario los completa RRHH despues.
    """
    resultado = db.execute(text("""
        INSERT INTO Employee (dni, name, email, gender, phone, birthDate, photo, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:dni, :name, :email, :gender, :phone, :birthDate, :photo, :updatedAt)
    """), {**datos, "updatedAt": datetime.now()})
    nuevo_id = resultado.scalar()
    db.commit()
    return nuevo_id


def crear_user(db: Session, usuario: str, email: str, password_hash: str,
               employee_id: int, origen: str, role_id: int = ROLE_USER) -> int:
    """
    El hash llega ya calculado. Cuando viene de un sistema externo que tambien
    usa bcrypt se copia tal cual, y el usuario nunca resetea su contrasena.
    """
    resultado = db.execute(text("""
        INSERT INTO [User] (usuario, email, password, roleId, employeeId, origen, activo, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:usuario, :email, :password, :roleId, :employeeId, :origen, 1, GETDATE())
    """), {
        "usuario": usuario,
        "email": email,
        "password": password_hash,
        "roleId": role_id,
        "employeeId": employee_id,
        "origen": origen,
    })
    nuevo_id = resultado.scalar()
    db.commit()
    return nuevo_id


def actualizar_password(db: Session, user_id: int, password_hash: str) -> None:
    """Sincroniza el hash local cuando cambio en el sistema de origen."""
    db.execute(text(
        "UPDATE [User] SET password = :p WHERE id = :id"
    ), {"p": password_hash, "id": user_id})
    db.commit()
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
py -m pytest tests/test_provisioning.py -v
```

Esperado: PASS, 13 tests.

- [ ] **Step 5: Colgar la migración del startup**

En `app/main.py`, agregar el import debajo de la línea `from app.database.asistencia import ensure_tables as ensure_tablas_asistencia`:

```python
from app.database.provisioning import ensure_columna_origen
```

Y dentro del bloque `try` de la función `startup()`, después de `ensure_tablas_asistencia(db)` y su `print`:

```python
        ensure_columna_origen(db)
        print("[OK] columna origen de [User] verificada")
```

- [ ] **Step 6: Verificar que la suite completa sigue pasando**

```bash
py -m pytest tests/ -v
```

Esperado: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/database/provisioning.py app/main.py tests/test_provisioning.py
git commit -m "feat: capa de datos del provisioning y columna [User].origen"
```

---

### Task 4: Proveedor ObraSocial

Los tres caminos del login institucional y la función `provisionar()` que Task 5 reutiliza para la importación masiva.

**Files:**
- Create: `app/database/obrasocial_usuarios.py`
- Create: `app/services/auth_providers/obrasocial.py`
- Modify: `app/services/auth_providers/__init__.py` (registrar el proveedor)
- Test: `tests/test_auth_obrasocial.py`

**Interfaces:**
- Consumes: `mapeo.persona_a_employee`, `mapeo.placeholder_email` (Task 1); `base.ResultadoAuth`, `local.verificar_password`, `fakes.FakeSession`, `fakes.hash_bcrypt` (Task 2); todo `app.database.provisioning` (Task 3).
- Produces:
  - `obrasocial_usuarios.buscar_por_nombre(db_os, nombre_usuario) -> Optional[dict]`
  - `obrasocial_usuarios.buscar_por_ids(db_os, id_usuarios: list[str]) -> list[dict]`
  - `obrasocial_usuarios.listar(db_os) -> list[dict]`
  - `obrasocial.provisionar(db: Session, externo: dict) -> tuple[int, int]` — devuelve `(employee_id, user_id)`
  - `obrasocial.ObraSocialAuthProvider(session_factory=SessionLocalObraSocial)` — la fábrica es inyectable para poder probar sin la base institucional

Las filas que devuelven las funciones de `obrasocial_usuarios` tienen estas claves: `idUsuario, nombreUsuario, claveUsuario, anulado, idPersona, nombrePersona, apellidoPersona, numeroDocPersona, sexoPersona, telefonoPersona, emailPersona, fechaNacPersona, fotoPersona`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_auth_obrasocial.py`:

```python
import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


HASH_SECRETO = hash_bcrypt("secreto")
HASH_NUEVO = hash_bcrypt("cambiada")

EXTERNO = {
    "idUsuario": "1915881e-fcf9-4caa-b5b0-998b6b314653",
    "nombreUsuario": "EmilianoRojo",
    "claveUsuario": HASH_SECRETO,
    "anulado": False,
    "idPersona": 232,
    "nombrePersona": "Emiliano",
    "apellidoPersona": "Rojo",
    "numeroDocPersona": "35123456",
    "sexoPersona": "M",
    "telefonoPersona": "3794123456",
    "emailPersona": "erojo@institucion.gob.ar",
    "fechaNacPersona": None,
    "fotoPersona": None,
}

USER_PROVISIONADO = {
    "id": 7,
    "usuario": "EmilianoRojo",
    "email": "erojo@institucion.gob.ar",
    "password": HASH_SECRETO,
    "roleId": 2,
    "employeeId": 264,
    "activo": True,
    "origen": "obrasocial",
}

USER_LOCAL = {**USER_PROVISIONADO, "id": 1, "usuario": "admin", "roleId": 1, "origen": "local"}


def _proveedor(externo=EXTERNO):
    """Proveedor con una sesion ObraSocial falsa que devuelve `externo`."""
    from app.services.auth_providers.obrasocial import ObraSocialAuthProvider

    filas = [externo] if externo else []
    sesion_os = FakeSession({"FROM [ObraSocial]": filas})
    return ObraSocialAuthProvider(session_factory=lambda: sesion_os), sesion_os


def _db(user_row=None, employee_row=None, user_vinculado=None,
        email_ocupado=False, nuevo_employee_id=300, nuevo_user_id=9):
    """Sesion RRHH falsa. Las claves son fragmentos distintivos de cada query."""
    return FakeSession({
        "FROM [User]\n        WHERE usuario": [user_row] if user_row else [],
        "SELECT id, dni, name FROM Employee": [employee_row] if employee_row else [],
        "SELECT id, usuario FROM [User]": [user_vinculado] if user_vinculado else [],
        "SELECT id FROM Employee WHERE email": [{"id": 1}] if email_ocupado else [],
        "INSERT INTO Employee": [{"id": nuevo_employee_id}],
        "INSERT INTO [User]": [{"id": nuevo_user_id}],
    })


# -- Camino 1: usuario local puro ---------------------------------------------

def test_usuario_local_no_consulta_obrasocial():
    proveedor, sesion_os = _proveedor()

    resultado = proveedor.autenticar(_db(user_row=USER_LOCAL), "admin", "secreto")

    assert resultado.roleId == 1
    assert sesion_os.ejecutadas == []


def test_usuario_local_inhabilitado_da_403():
    proveedor, _ = _proveedor()
    inactivo = {**USER_LOCAL, "activo": False}

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=inactivo), "admin", "secreto")
    assert e.value.status_code == 403


# -- Camino 2: usuario ya provisionado ----------------------------------------

def test_usuario_provisionado_entra_con_su_hash_local():
    proveedor, _ = _proveedor()

    resultado = proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "secreto")

    assert resultado.usuario == "EmilianoRojo"
    assert resultado.employeeId == 264


def test_usuario_anulado_en_obrasocial_da_403():
    proveedor, _ = _proveedor({**EXTERNO, "anulado": True})

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "secreto")

    assert e.value.status_code == 403
    assert "institución" in e.value.detail


def test_clave_cambiada_en_obrasocial_se_sincroniza_y_deja_entrar():
    proveedor, _ = _proveedor({**EXTERNO, "claveUsuario": HASH_NUEVO})
    db = _db(user_row=USER_PROVISIONADO)

    resultado = proveedor.autenticar(db, "EmilianoRojo", "cambiada")

    assert resultado.employeeId == 264
    assert "UPDATE [User] SET password" in db.sql_ejecutado()


def test_clave_sin_cambios_no_escribe_en_la_base():
    proveedor, _ = _proveedor()
    db = _db(user_row=USER_PROVISIONADO)

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert "UPDATE [User] SET password" not in db.sql_ejecutado()


def test_password_incorrecta_de_usuario_provisionado_da_401():
    proveedor, _ = _proveedor()

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(user_row=USER_PROVISIONADO), "EmilianoRojo", "otra")
    assert e.value.status_code == 401


# -- Camino 3: primer login ---------------------------------------------------

def test_primer_login_crea_employee_y_user():
    proveedor, _ = _proveedor()
    db = _db()

    resultado = proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert resultado.usuario == "EmilianoRojo"
    assert resultado.roleId == 2
    assert resultado.employeeId == 300
    sql = db.sql_ejecutado()
    assert "INSERT INTO Employee" in sql
    assert "INSERT INTO [User]" in sql


def test_primer_login_copia_el_hash_de_obrasocial():
    proveedor, _ = _proveedor()
    db = _db()

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    inserts = [p for sql, p in db.ejecutadas if "INSERT INTO [User]" in sql]
    assert inserts[0]["password"] == HASH_SECRETO
    assert inserts[0]["origen"] == "obrasocial"


def test_primer_login_reutiliza_el_employee_existente_por_dni():
    proveedor, _ = _proveedor()
    db = _db(employee_row={"id": 264, "dni": "35123456", "name": "Emiliano Rojo"})

    resultado = proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert resultado.employeeId == 264
    assert "INSERT INTO Employee" not in db.sql_ejecutado()


def test_usuario_inexistente_en_ambos_lados_da_401():
    proveedor, _ = _proveedor(externo=None)

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(), "fantasma", "secreto")
    assert e.value.status_code == 401


def test_password_incorrecta_no_provisiona_nada():
    proveedor, _ = _proveedor()
    db = _db()

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(db, "EmilianoRojo", "otra")

    assert e.value.status_code == 401
    assert "INSERT INTO" not in db.sql_ejecutado()


def test_anulado_no_provisiona_nada():
    proveedor, _ = _proveedor({**EXTERNO, "anulado": True})
    db = _db()

    with pytest.raises(HTTPException):
        proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert "INSERT INTO" not in db.sql_ejecutado()


# -- Casos borde del provisioning ---------------------------------------------

def test_persona_sin_dni_da_400():
    proveedor, _ = _proveedor({**EXTERNO, "numeroDocPersona": None})

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(_db(), "EmilianoRojo", "secreto")

    assert e.value.status_code == 400
    assert "documento" in e.value.detail


def test_dni_ya_vinculado_a_otro_usuario_da_409():
    proveedor, _ = _proveedor()
    db = _db(
        employee_row={"id": 264, "dni": "35123456", "name": "Emiliano Rojo"},
        user_vinculado={"id": 3, "usuario": "otro.usuario"},
    )

    with pytest.raises(HTTPException) as e:
        proveedor.autenticar(db, "EmilianoRojo", "secreto")

    assert e.value.status_code == 409
    assert "otro.usuario" in e.value.detail


def test_email_duplicado_cae_al_placeholder():
    proveedor, _ = _proveedor()
    db = _db(email_ocupado=True)

    proveedor.autenticar(db, "EmilianoRojo", "secreto")

    inserts = [p for sql, p in db.ejecutadas if "INSERT INTO Employee" in sql]
    assert inserts[0]["email"] == "EmilianoRojo@sin-email.local"


# -- Registro del proveedor ---------------------------------------------------

def test_get_provider_devuelve_el_proveedor_institucional(monkeypatch):
    from app.services import auth_providers
    from app.services.auth_providers.obrasocial import ObraSocialAuthProvider

    monkeypatch.setenv("AUTH_PROVIDER", "obrasocial")
    assert isinstance(auth_providers.get_provider(), ObraSocialAuthProvider)


# -- Consultas a la base institucional ----------------------------------------

def test_buscar_por_ids_arma_el_in_con_binds():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})
    os_db.buscar_por_ids(db_os, ["aaa", "bbb"])

    sql, params = db_os.ejecutadas[0]
    assert ":id0, :id1" in sql
    assert params == {"id0": "aaa", "id1": "bbb"}
    assert "aaa" not in sql


def test_buscar_por_ids_con_lista_vacia_no_consulta():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession()
    assert os_db.buscar_por_ids(db_os, []) == []
    assert db_os.ejecutadas == []


def test_las_consultas_institucionales_son_de_solo_lectura():
    from app.database import obrasocial_usuarios as os_db

    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})
    os_db.listar(db_os)
    os_db.buscar_por_nombre(db_os, "EmilianoRojo")
    os_db.buscar_por_ids(db_os, ["aaa"])

    sql = db_os.sql_ejecutado().upper()
    for prohibido in ("INSERT", "UPDATE", "DELETE", "MERGE", "DROP"):
        assert prohibido not in sql
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_auth_obrasocial.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.auth_providers.obrasocial'`

- [ ] **Step 3: Escribir las consultas a la base institucional**

Crear `app/database/obrasocial_usuarios.py`:

```python
"""
Lecturas sobre la base institucional.

Es de SOLO LECTURA: el sistema RRHH nunca escribe en ObraSocial. Cualquier
INSERT, UPDATE o DELETE contra [ObraSocial].[dbo].* es un bug.

Usuario y Persona se consultan siempre juntos: sin los datos de la persona no
se puede vincular ni crear el empleado, asi que separarlos solo agregaria un
viaje de ida y vuelta.
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_SELECT_USUARIO = """
    SELECT u.idUsuario, u.nombreUsuario, u.claveUsuario, u.anulado, u.idPersona,
           p.nombrePersona, p.apellidoPersona, p.numeroDocPersona,
           p.sexoPersona, p.telefonoPersona, p.emailPersona,
           p.fechaNacPersona, p.fotoPersona
    FROM [ObraSocial].[dbo].[Usuario] u
    LEFT JOIN [ObraSocial].[dbo].[Persona] p ON p.idPersona = u.idPersona
"""


def buscar_por_nombre(db_os: Session, nombre_usuario: str) -> Optional[dict]:
    fila = db_os.execute(
        text(_SELECT_USUARIO + " WHERE u.nombreUsuario = :n"),
        {"n": nombre_usuario},
    ).mappings().first()
    return dict(fila) if fila else None


def buscar_por_ids(db_os: Session, id_usuarios: list[str]) -> list[dict]:
    """Los binds se generan: ningun valor entra interpolado en el SQL."""
    if not id_usuarios:
        return []
    binds = {f"id{i}": valor for i, valor in enumerate(id_usuarios)}
    marcadores = ", ".join(f":{clave}" for clave in binds)
    filas = db_os.execute(
        text(_SELECT_USUARIO + f" WHERE u.idUsuario IN ({marcadores})"),
        binds,
    ).mappings().all()
    return [dict(f) for f in filas]


def listar(db_os: Session) -> list[dict]:
    filas = db_os.execute(
        text(_SELECT_USUARIO + " ORDER BY p.apellidoPersona, p.nombrePersona")
    ).mappings().all()
    return [dict(f) for f in filas]
```

- [ ] **Step 4: Escribir el proveedor**

Crear `app/services/auth_providers/obrasocial.py`:

```python
"""
Proveedor institucional: valida contra la base ObraSocial y provisiona el
usuario local en el primer login.

Tres caminos, segun el estado del usuario en la base de RRHH:

  1. Existe con origen 'local'       -> se valida solo local, ObraSocial ni
                                        se consulta. Es el admin creado a mano.
  2. Existe con origen 'obrasocial'  -> se verifica la baja y se sincroniza el
                                        hash, despues se valida local.
  3. No existe                       -> se valida contra ObraSocial y se
                                        provisiona Employee y [User].

Los dos sistemas hashean con bcrypt en el mismo formato, asi que el hash se
copia tal cual y el usuario nunca resetea su contrasena.

Las dos bases viven en el mismo servidor: si ObraSocial cae, la base de RRHH
cae tambien y no hay login posible por ningun camino. Por eso no hay ningun
fallback ni modo degradado -- seria codigo muerto.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import obrasocial_usuarios as os_db
from app.database import provisioning as prov
from app.database.database import SessionLocalObraSocial
from app.services.auth_providers.base import ResultadoAuth
from app.services.auth_providers.local import verificar_password
from app.services.auth_providers.mapeo import persona_a_employee, placeholder_email


def provisionar(db: Session, externo: dict) -> tuple[int, int]:
    """
    Crea (o reutiliza) el Employee y crea el [User] para una persona de
    ObraSocial. Retorna (employee_id, user_id).

    No valida contrasena: el login la valida antes de llamar, y la importacion
    desde RRHH no la necesita.
    """
    nombre_usuario = externo["nombreUsuario"]

    try:
        datos = persona_a_employee(externo, nombre_usuario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    existente = prov.buscar_employee_por_dni(db, datos["dni"])
    if existente is not None:
        employee_id = existente["id"]
        ya_vinculado = prov.user_de_employee(db, employee_id)
        if ya_vinculado is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El DNI {datos['dni']} ya está vinculado al usuario "
                    f"'{ya_vinculado['usuario']}'. Requiere revisión manual."
                ),
            )
    else:
        # Employee.email es unico. Si el de la persona ya lo usa otro empleado
        # se cae al placeholder, que queda visible para que RRHH lo corrija.
        if prov.email_ocupado(db, datos["email"]):
            datos["email"] = placeholder_email(nombre_usuario)
        employee_id = prov.crear_employee(db, datos)

    user_id = prov.crear_user(
        db,
        usuario=nombre_usuario,
        email=datos["email"],
        password_hash=externo["claveUsuario"],
        employee_id=employee_id,
        origen=prov.ORIGEN_OBRASOCIAL,
    )
    return employee_id, user_id


class ObraSocialAuthProvider:
    def __init__(self, session_factory=SessionLocalObraSocial):
        # Inyectable para poder probar sin la base institucional.
        self._session_factory = session_factory

    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        local = prov.buscar_user(db, usuario)

        if local is not None and local["origen"] == prov.ORIGEN_LOCAL:
            return self._camino_local(local, password)

        db_os = self._session_factory()
        try:
            externo = os_db.buscar_por_nombre(db_os, usuario)
        finally:
            db_os.close()

        if externo is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        if externo["anulado"]:
            raise HTTPException(
                status_code=403, detail="Acceso denegado por la institución"
            )

        if local is not None:
            return self._camino_provisionado(db, local, externo, password)
        return self._camino_primer_login(db, externo, password)

    def _camino_local(self, local: dict, password: str) -> ResultadoAuth:
        if not local["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")
        verificar_password(password, local["password"])
        return _a_resultado(local)

    def _camino_provisionado(self, db: Session, local: dict, externo: dict,
                             password: str) -> ResultadoAuth:
        if not local["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")

        # El usuario pudo cambiar su clave en ObraSocial. La consulta de arriba
        # ya trajo el hash vigente, asi que sincronizarlo no cuesta un viaje mas.
        hash_vigente = externo["claveUsuario"]
        if hash_vigente != local["password"]:
            prov.actualizar_password(db, local["id"], hash_vigente)
            local = {**local, "password": hash_vigente}

        verificar_password(password, local["password"])
        return _a_resultado(local)

    def _camino_primer_login(self, db: Session, externo: dict,
                             password: str) -> ResultadoAuth:
        # Validar antes de provisionar: una contrasena incorrecta no debe
        # dejar un Employee huerfano en la base.
        verificar_password(password, externo["claveUsuario"])
        employee_id, _ = provisionar(db, externo)
        return ResultadoAuth(
            usuario=externo["nombreUsuario"],
            roleId=prov.ROLE_USER,
            employeeId=employee_id,
        )


def _a_resultado(local: dict) -> ResultadoAuth:
    return ResultadoAuth(
        usuario=local["usuario"],
        roleId=local["roleId"],
        employeeId=local["employeeId"],
    )
```

- [ ] **Step 5: Registrar el proveedor**

En `app/services/auth_providers/__init__.py`, agregar el import debajo del de `LocalAuthProvider`:

```python
from app.services.auth_providers.obrasocial import ObraSocialAuthProvider
```

Y reemplazar el diccionario `_PROVEEDORES` (junto con el comentario que lo precede) por:

```python
_PROVEEDORES = {
    "local": LocalAuthProvider,
    "obrasocial": ObraSocialAuthProvider,
}
```

- [ ] **Step 6: Correr los tests para verificar que pasan**

```bash
py -m pytest tests/test_auth_obrasocial.py -v
```

Esperado: PASS, 19 tests.

- [ ] **Step 7: Verificar que la suite completa sigue pasando**

```bash
py -m pytest tests/ -v
```

Esperado: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/database/obrasocial_usuarios.py app/services/auth_providers/ tests/test_auth_obrasocial.py
git commit -m "feat: proveedor institucional con provisioning on-demand por DNI"
```

---

### Task 5: Endpoints de configuración e importación

Expone el modo de autenticación al frontend y da a RRHH la vía para importar usuarios sin esperar a que entren por primera vez.

**Files:**
- Modify: `app/routes/auth.py` (agregar `GET /config` al final)
- Modify: `app/routes/obrasocial.py` (reescribir completo)
- Test: `tests/test_obrasocial_endpoints.py`

**Interfaces:**
- Consumes: `nombre_proveedor()` (Task 2); `provisioning.buscar_user`, `provisioning.employees_por_dni` (Task 3); `obrasocial_usuarios.listar`, `obrasocial_usuarios.buscar_por_ids`, `obrasocial.provisionar` (Task 4).
- Produces:
  - `GET /auth/config` → `{"authProvider": "local" | "obrasocial"}` — público
  - `GET /obrasocial/usuarios` → `{"usuarios": [...]}` — requiere ADMIN
  - `POST /obrasocial/importar` con cuerpo `{"idUsuarios": [...]}` → `{"importados": int, "ya_existian": int, "errores": [{"idUsuario": str, "motivo": str}]}` — requiere ADMIN
  - `obrasocial.fila_usuario(externo: dict, vinculos: dict[str, int]) -> dict` — función pura que arma la fila de respuesta

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_obrasocial_endpoints.py`:

```python
import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


EXTERNO = {
    "idUsuario": "1915881e-fcf9-4caa-b5b0-998b6b314653",
    "nombreUsuario": "EmilianoRojo",
    "claveUsuario": hash_bcrypt("secreto"),
    "anulado": False,
    "idPersona": 232,
    "nombrePersona": "Emiliano",
    "apellidoPersona": "Rojo",
    "numeroDocPersona": "35123456",
    "sexoPersona": "M",
    "telefonoPersona": "3794123456",
    "emailPersona": "erojo@institucion.gob.ar",
    "fechaNacPersona": None,
    "fotoPersona": None,
}


# -- fila_usuario -------------------------------------------------------------

def test_fila_marca_vinculado_cuando_el_dni_existe():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {"35123456": 264})

    assert fila["vinculado"] is True
    assert fila["employeeId"] == 264
    assert fila["dni"] == "35123456"
    assert fila["nombreUsuario"] == "EmilianoRojo"
    assert fila["anulado"] is False


def test_fila_marca_no_vinculado_cuando_el_dni_no_existe():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {})

    assert fila["vinculado"] is False
    assert fila["employeeId"] is None


def test_fila_de_persona_sin_dni_no_explota():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario({**EXTERNO, "numeroDocPersona": None}, {"35123456": 264})

    assert fila["dni"] == ""
    assert fila["vinculado"] is False


def test_fila_nunca_expone_la_clave():
    from app.routes.obrasocial import fila_usuario

    fila = fila_usuario(EXTERNO, {})

    assert "claveUsuario" not in fila
    assert EXTERNO["claveUsuario"] not in str(fila)


# -- importar_usuarios --------------------------------------------------------

def _db_vacia():
    return FakeSession({
        "INSERT INTO Employee": [{"id": 300}],
        "INSERT INTO [User]": [{"id": 9}],
    })


def test_importar_da_de_alta_un_usuario_nuevo():
    from app.routes.obrasocial import importar_usuarios

    db = _db_vacia()
    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})

    resumen = importar_usuarios(db, db_os, [EXTERNO["idUsuario"]])

    assert resumen == {"importados": 1, "ya_existian": 0, "errores": []}
    assert "INSERT INTO Employee" in db.sql_ejecutado()


def test_importar_saltea_a_quien_ya_tiene_usuario():
    from app.routes.obrasocial import importar_usuarios

    db = FakeSession({
        "FROM [User]\n        WHERE usuario": [{"id": 7, "usuario": "EmilianoRojo", "origen": "obrasocial"}],
    })
    db_os = FakeSession({"FROM [ObraSocial]": [EXTERNO]})

    resumen = importar_usuarios(db, db_os, [EXTERNO["idUsuario"]])

    assert resumen["ya_existian"] == 1
    assert resumen["importados"] == 0
    assert "INSERT INTO" not in db.sql_ejecutado()


def test_un_elemento_fallido_no_aborta_el_lote():
    from app.routes.obrasocial import importar_usuarios

    sin_dni = {**EXTERNO, "idUsuario": "otro-id", "nombreUsuario": "SinDni",
               "numeroDocPersona": None}
    db = _db_vacia()
    db_os = FakeSession({"FROM [ObraSocial]": [sin_dni, EXTERNO]})

    resumen = importar_usuarios(db, db_os, ["otro-id", EXTERNO["idUsuario"]])

    assert resumen["importados"] == 1
    assert len(resumen["errores"]) == 1
    assert resumen["errores"][0]["idUsuario"] == "otro-id"
    assert "documento" in resumen["errores"][0]["motivo"]


def test_importar_sin_ids_es_un_400():
    from app.routes.obrasocial import importar_usuarios

    with pytest.raises(HTTPException) as e:
        importar_usuarios(_db_vacia(), FakeSession(), [])
    assert e.value.status_code == 400
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_obrasocial_endpoints.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'fila_usuario' from 'app.routes.obrasocial'`

- [ ] **Step 3: Reescribir el router de ObraSocial**

Reemplazar el contenido completo de `app/routes/obrasocial.py`:

```python
"""
Puente con la base institucional.

GET  /obrasocial/usuarios  lista los usuarios de la institucion indicando
                           cuales ya estan vinculados a un empleado de RRHH.
POST /obrasocial/importar  da de alta a los seleccionados sin esperar a que
                           entren por primera vez.

Ambos requieren rol ADMIN: exponen datos personales (documento, telefono,
email) de toda la planta.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth_middleware import ROLE_ADMIN, require_roles
from app.database import obrasocial_usuarios as os_db
from app.database import provisioning as prov
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.services.auth_providers.obrasocial import provisionar

router = APIRouter(prefix="/obrasocial", tags=["ObraSocial"])

SOLO_ADMIN = Depends(require_roles(ROLE_ADMIN))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_obrasocial_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()


def fila_usuario(externo: dict, vinculos: dict[str, int]) -> dict:
    """
    La fila que ve el tablero de RRHH. Nunca incluye claveUsuario: el hash de
    la institucion no tiene por que salir de la capa de autenticacion.
    """
    dni = str(externo.get("numeroDocPersona") or "").strip()
    employee_id = vinculos.get(dni)
    return {
        "idUsuario": str(externo["idUsuario"]),
        "nombreUsuario": externo["nombreUsuario"],
        "anulado": bool(externo["anulado"]),
        "nombre": externo.get("nombrePersona"),
        "apellido": externo.get("apellidoPersona"),
        "dni": dni,
        "email": externo.get("emailPersona"),
        "telefono": externo.get("telefonoPersona"),
        "vinculado": employee_id is not None,
        "employeeId": employee_id,
    }


def importar_usuarios(db: Session, db_os: Session, id_usuarios: list[str]) -> dict:
    """
    Provisiona el lote. Un elemento que falla se registra y el resto sigue:
    abortar todo por un documento faltante obligaria a RRHH a depurar la lista
    a mano antes de cada intento.
    """
    if not id_usuarios:
        raise HTTPException(status_code=400, detail="Falta la lista idUsuarios")

    externos = os_db.buscar_por_ids(db_os, [str(i) for i in id_usuarios])
    importados = 0
    ya_existian = 0
    errores = []

    for externo in externos:
        try:
            if prov.buscar_user(db, externo["nombreUsuario"]) is not None:
                ya_existian += 1
                continue
            provisionar(db, externo)
            importados += 1
        except HTTPException as e:
            db.rollback()
            errores.append({"idUsuario": str(externo["idUsuario"]), "motivo": str(e.detail)})
        except Exception as e:
            db.rollback()
            errores.append({"idUsuario": str(externo["idUsuario"]), "motivo": str(e)})

    return {"importados": importados, "ya_existian": ya_existian, "errores": errores}


@router.get("/usuarios", dependencies=[SOLO_ADMIN])
def get_usuarios(db: Session = Depends(get_db),
                 db_os: Session = Depends(get_obrasocial_db)):
    try:
        externos = os_db.listar(db_os)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error al consultar la base institucional: {e}",
        )

    dnis = [
        str(u["numeroDocPersona"]).strip()
        for u in externos
        if u.get("numeroDocPersona")
    ]
    vinculos = prov.employees_por_dni(db, dnis)
    return {"usuarios": [fila_usuario(u, vinculos) for u in externos]}


@router.post("/importar", dependencies=[SOLO_ADMIN])
async def importar(request: Request, db: Session = Depends(get_db),
                   db_os: Session = Depends(get_obrasocial_db)):
    body = await request.json()
    ids = body.get("idUsuarios")
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Falta la lista idUsuarios")
    return importar_usuarios(db, db_os, ids)
```

- [ ] **Step 4: Agregar el endpoint de configuración**

En `app/routes/auth.py`, cambiar el import de `auth_providers` para traer también `nombre_proveedor`:

```python
from app.services.auth_providers import get_provider, nombre_proveedor
```

Y agregar al final del archivo:

```python
# ---------------------------------------------------------------------------
# ⚙️ CONFIG — Modo de autenticación activo
# ---------------------------------------------------------------------------
@router.get("/config")
def get_auth_config():
    """
    Publico a proposito: el frontend lo consulta antes de cualquier login para
    saber que pantallas mostrar. No expone nada sensible, solo que modo esta
    activo.
    """
    return {"authProvider": nombre_proveedor()}
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

```bash
py -m pytest tests/test_obrasocial_endpoints.py -v
```

Esperado: PASS, 9 tests.

- [ ] **Step 6: Verificar que la suite completa sigue pasando**

```bash
py -m pytest tests/ -v
```

Esperado: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/obrasocial.py app/routes/auth.py tests/test_obrasocial_endpoints.py
git commit -m "feat: endpoints de config de auth e importacion de usuarios institucionales"
```

---

### Task 6: Tab de importación en la pantalla Admin

El tab solo aparece cuando `authProvider` es `obrasocial`. En la versión comercial la pantalla Admin queda idéntica a como está hoy.

**Files:**
- Create: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\Admin\ObraSocialUsuariosTab.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Interfas\Interfaces.ts` (agregar interface al final)
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\screens\Admin\Screen.tsx`

**Interfaces:**
- Consumes: `GET /auth/config`, `GET /obrasocial/usuarios`, `POST /obrasocial/importar` (Task 5).
- Produces: `UsuarioObraSocial` en `Interfaces.ts`; el componente `ObraSocialUsuariosTab`.

**Nota sobre el repositorio:** este task se trabaja en `C:\Users\Emiliano\Documents\RRHH` (frontend), sobre la rama `main`. Los tasks anteriores son del backend.

- [ ] **Step 1: Agregar la interface**

Al final de `src/app/Interfas/Interfaces.ts`:

```ts
/** Fila del tablero de importación de usuarios institucionales. */
export interface UsuarioObraSocial {
  idUsuario: string;
  nombreUsuario: string;
  anulado: boolean;
  nombre: string | null;
  apellido: string | null;
  dni: string;
  email: string | null;
  telefono: string | null;
  vinculado: boolean;
  employeeId: number | null;
}
```

- [ ] **Step 2: Escribir el componente**

Crear `src/app/Componentes/Admin/ObraSocialUsuariosTab.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/app/util/apiClient";
import { UsuarioObraSocial } from "@/app/Interfas/Interfaces";

interface ResumenImportacion {
  importados: number;
  ya_existian: number;
  errores: { idUsuario: string; motivo: string }[];
}

export function ObraSocialUsuariosTab() {
  const [usuarios, setUsuarios] = useState<UsuarioObraSocial[]>([]);
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [busqueda, setBusqueda] = useState("");
  const [cargando, setCargando] = useState(true);
  const [importando, setImportando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumen, setResumen] = useState<ResumenImportacion | null>(null);

  const cargar = async () => {
    setCargando(true);
    try {
      const r = await apiClient.get<{ usuarios: UsuarioObraSocial[] }>(
        "/obrasocial/usuarios",
      );
      setUsuarios(r.usuarios);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los usuarios");
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    cargar();
  }, []);

  const filtrados = useMemo(() => {
    const termino = busqueda.trim().toLowerCase();
    if (!termino) return usuarios;
    return usuarios.filter((u) =>
      [u.nombreUsuario, u.nombre, u.apellido, u.dni]
        .filter(Boolean)
        .some((campo) => String(campo).toLowerCase().includes(termino)),
    );
  }, [usuarios, busqueda]);

  // Solo tiene sentido importar a quien no esta vinculado y no fue dado de baja.
  const importables = useMemo(
    () => filtrados.filter((u) => !u.vinculado && !u.anulado),
    [filtrados],
  );

  const alternar = (id: string) => {
    setSeleccion((previa) => {
      const siguiente = new Set(previa);
      if (siguiente.has(id)) siguiente.delete(id);
      else siguiente.add(id);
      return siguiente;
    });
  };

  const alternarTodos = () => {
    setSeleccion((previa) =>
      previa.size === importables.length
        ? new Set()
        : new Set(importables.map((u) => u.idUsuario)),
    );
  };

  const importar = async () => {
    if (seleccion.size === 0) return;
    setImportando(true);
    setResumen(null);
    try {
      const r = await apiClient.post<ResumenImportacion>("/obrasocial/importar", {
        idUsuarios: Array.from(seleccion),
      });
      setResumen(r);
      setSeleccion(new Set());
      await cargar();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falló la importación");
    } finally {
      setImportando(false);
    }
  };

  if (cargando) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-2xl mb-2" />
        <p>Cargando usuarios de la institución…</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground">
            Usuarios de la institución
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Importalos para que RRHH pueda completar sus datos antes de que entren
            por primera vez.
          </p>
        </div>
        <button
          onClick={importar}
          disabled={importando || seleccion.size === 0}
          className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 disabled:opacity-50 whitespace-nowrap"
        >
          {importando ? "Importando…" : `Importar ${seleccion.size} seleccionados`}
        </button>
      </div>

      <input
        value={busqueda}
        onChange={(e) => setBusqueda(e.target.value)}
        placeholder="Buscar por usuario, nombre o DNI…"
        className="w-full sm:w-80 mb-4 px-3 py-2 rounded-md bg-muted border border-border text-foreground text-sm"
      />

      {error && (
        <div className="mb-4 p-3 rounded-md bg-error/10 text-error text-sm">{error}</div>
      )}

      {resumen && (
        <div className="mb-4 p-3 rounded-md bg-muted text-sm text-foreground">
          <p>
            Importados: <strong>{resumen.importados}</strong> · Ya existían:{" "}
            <strong>{resumen.ya_existian}</strong>
          </p>
          {resumen.errores.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-error">
              {resumen.errores.map((e) => (
                <li key={e.idUsuario}>{e.motivo}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th className="py-2 pr-4 w-10">
                <input
                  type="checkbox"
                  checked={importables.length > 0 && seleccion.size === importables.length}
                  onChange={alternarTodos}
                  disabled={importables.length === 0}
                  aria-label="Seleccionar todos los importables"
                />
              </th>
              <th className="py-2 pr-4">Usuario</th>
              <th className="py-2 pr-4">Nombre</th>
              <th className="py-2 pr-4">DNI</th>
              <th className="py-2 pr-4">Email</th>
              <th className="py-2">Estado</th>
            </tr>
          </thead>
          <tbody>
            {filtrados.map((u) => {
              const importable = !u.vinculado && !u.anulado;
              return (
                <tr key={u.idUsuario} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4">
                    <input
                      type="checkbox"
                      checked={seleccion.has(u.idUsuario)}
                      onChange={() => alternar(u.idUsuario)}
                      disabled={!importable}
                      aria-label={`Seleccionar ${u.nombreUsuario}`}
                    />
                  </td>
                  <td className="py-2 pr-4 text-foreground">{u.nombreUsuario}</td>
                  <td className="py-2 pr-4">
                    {[u.nombre, u.apellido].filter(Boolean).join(" ") || "—"}
                  </td>
                  <td className="py-2 pr-4">{u.dni || "—"}</td>
                  <td className="py-2 pr-4">{u.email || "—"}</td>
                  <td className="py-2">
                    {u.anulado ? (
                      <span className="text-error">Dado de baja</span>
                    ) : u.vinculado ? (
                      <span className="text-success">Vinculado</span>
                    ) : (
                      <span className="text-muted-foreground">Pendiente</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {filtrados.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-muted-foreground">
                  No hay usuarios que coincidan con la búsqueda.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Conectar el tab condicional**

En `src/app/screens/Admin/Screen.tsx`:

Agregar los imports junto a los que ya existen al principio del archivo:

```tsx
import { apiClient } from '@/app/util/apiClient';
import { ObraSocialUsuariosTab } from '@/app/Componentes/Admin/ObraSocialUsuariosTab';
```

Agregar el estado junto a los demás `useState` (después de `const [activeTab, setActiveTab] = useState<string>('active-users');`):

```tsx
    const [authProvider, setAuthProvider] = useState<string>('local');
```

Agregar el efecto que lo consulta, junto al `useEffect` que ya carga usuarios y roles:

```tsx
    useEffect(() => {
        apiClient.get<{ authProvider: string }>('/auth/config')
            .then((r) => setAuthProvider(r.authProvider))
            .catch(() => setAuthProvider('local'));
    }, []);
```

Reemplazar el bloque `<nav>` de los tabs por:

```tsx
                        <nav className="-mb-px flex space-x-2 sm:space-x-6 overflow-x-auto">
                            <TabButton id="active-users" title="Usuarios Activos" />
                            <TabButton id="inactive-users" title="Usuarios Inactivos" />
                            <TabButton id="roles" title="Configuración de Roles" />
                            <TabButton id="profiles" title="Perfiles de Usuario" />
                            {authProvider === 'obrasocial' && (
                                <TabButton id="obrasocial" title="Usuarios ObraSocial" />
                            )}
                        </nav>
```

Y reemplazar la línea que renderiza el tab de perfiles por esas dos:

```tsx
                        {activeTab === 'profiles' && <ProfileSettings />}
                        {activeTab === 'obrasocial' && authProvider === 'obrasocial' && <ObraSocialUsuariosTab />}
```

- [ ] **Step 4: Verificar tipos**

```bash
npx tsc --noEmit
```

Esperado: el proyecto ya arrastra errores previos en `Productivity.tsx`, `LicenseModal.tsx`, `BasicFields.tsx`, `EntityFormModal.tsx`, `data-grouping.ts`, `department-analyzer.ts`, `insight-generator.ts` y `prompt-builder.ts`. Ninguno nuevo puede aparecer en `ObraSocialUsuariosTab.tsx`, `Screen.tsx` ni `Interfaces.ts`. Si alguno de esos tres aparece en la salida, corregirlo antes de seguir.

- [ ] **Step 5: Commit**

```bash
git add src/app/Componentes/Admin/ObraSocialUsuariosTab.tsx src/app/screens/Admin/Screen.tsx src/app/Interfas/Interfaces.ts
git commit -m "feat: tab de importacion de usuarios institucionales en Admin"
```

---

## Verificación final

Después de la última tarea, con el backend en la rama `auth-obrasocial-institucional`:

- [ ] **Suite completa del backend**

```bash
py -m pytest tests/ -v
```

Esperado: PASS, sin tests salteados.

- [ ] **El modo comercial no cambió**

Sin `AUTH_PROVIDER` en el `.env`, `nombre_proveedor()` devuelve `'local'`, el login usa `LocalAuthProvider` y `GET /auth/config` devuelve `{"authProvider": "local"}`. El tab de ObraSocial no se renderiza. Confirmar con:

```bash
py -m pytest tests/test_auth_provider_local.py -v
```

- [ ] **Activar el modo institucional**

Agregar al `.env` del backend (archivo local, no se commitea):

```
AUTH_PROVIDER=obrasocial
```

Al reiniciar el servidor, el startup debe imprimir `[OK] columna origen de [User] verificada`.
