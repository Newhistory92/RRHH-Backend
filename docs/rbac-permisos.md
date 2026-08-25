# RBAC Data-Driven — Referencia de Permisos

> **Estado:** producción · Implementado en `claude/practical-keller-f5f105`

## Principio

Ningún rol se identifica por ID numérico en la lógica de autorización. Todo se
basa en **códigos de permiso** (`string`) almacenados en las tablas `Permission`
y `RolePermission` de la base de datos.

---

## Catálogo de permisos

| Código | Descripción |
|---|---|
| `rrhh.gestionar` | Alta, baja y modificación de empleados, contratos, etc. |
| `asistencia.gestionar` | Aprobar ausencias, gestionar marcaciones |
| `licencias.configurar` | Configurar tipos de licencia y feriados |
| `activos.inventario` | Ver y editar inventario de activos |
| `activos.configurar` | Configurar categorías y modelos de activos |
| `activos.modelos` | Administrar modelos de activos |
| `publicaciones.gestionar` | Crear y editar publicaciones internas |
| `inicio.ver` | Ver el feed de inicio |
| `estadisticas.ver` | Acceder al módulo de estadísticas |
| `reubicacion.gestionar` | Gestionar propuestas de reubicación inteligente |
| `reubicacion.solicitar` | Auto-postularse a reubicaciones disponibles |
| `feedback.participar` | Responder encuestas de feedback |
| `feedback.configurar` | Crear y cerrar rondas de feedback |
| `test.gestionar` | Configurar tests técnicos y soft skills |
| `organigrama.ver` | Ver el organigrama |
| `organigrama.gestionar` | Modificar departamentos y oficinas |
| `admin.gestionar` | Administración: usuarios, roles, ObraSocial |
| `ia.usar` | Acceder al módulo de IA (reservado, chat.py no implementado aún) |

**Comodín:** el código `*` (asignado al rol `Admin`) pasa cualquier verificación.

---

## Asignación por rol (seed)

Definida en `app/database/permissions.py → sembrar()`. El seed es **idempotente**:
solo inserta lo que falta al iniciar el servidor.

| Rol | Permisos |
|---|---|
| **Admin** | `*` (todos) |
| **RRHH** | `rrhh.gestionar`, `asistencia.gestionar`, `licencias.configurar`, `publicaciones.gestionar`, `inicio.ver`, `estadisticas.ver`, `reubicacion.gestionar`, `feedback.configurar`, `test.gestionar`, `organigrama.gestionar` |
| **User** | `inicio.ver`, `reubicacion.solicitar`, `feedback.participar`, `test.gestionar`, `organigrama.ver` |
| **Estadista** | `estadisticas.ver`, `inicio.ver`, `organigrama.ver` |
| **Tecnico** | `activos.inventario`, `activos.configurar`, `activos.modelos`, `inicio.ver` |
| **Patrimonio** | `activos.inventario`, `inicio.ver` |

---

## Flujo de autorización

```
JWT → get_current_user → permisos_de_rol(db, role_id) → set[str]
                                                            ↓
                                              require_permission("codigo")
                                                            ↓
                                              _autorizar(user, "codigo")
                                                  tiene_permiso() → 200 / 403
```

1. **`get_current_user`** (`app/auth_middleware.py`): decodifica el JWT y llama
   `permisos_de_rol` en cada request — nunca lee los permisos del token.
2. **`require_permission(code)`**: dependency factory de FastAPI que llama
   `_autorizar`. Si falla, devuelve `403` con el código requerido en el detalle.
3. **`require_auth`**: dependency para endpoints accesibles a cualquier usuario
   autenticado, sin restricción de permiso.

---

## Frontend

- `src/app/util/permisos.ts` — `leerPermisos()`, `guardarPermisos()`,
  `limpiarPermisos()`, `tienePermiso(code)` (localStorage + SSR guard).
- `src/app/util/rbac.ts` — `PAGE_CONFIG[]` con campo `permiso: string` por
  página. Sin constantes `ROLE_ID`. `canAccess()`, `getSidebarPages()`,
  `getDefaultPage()`.
- Al hacer login, el backend devuelve `"permisos": [...]` (array ordenado);
  el frontend los guarda con `guardarPermisos()`.

---

## Archivos clave

| Archivo | Responsabilidad |
|---|---|
| `app/permisos.py` | Catálogo `PERMISOS`, `COMODIN`, `tiene_permiso()` |
| `app/database/permissions.py` | DDL + seed idempotente + `permisos_de_rol()` |
| `app/auth_middleware.py` | `require_permission()`, `require_auth`, `_autorizar()`, `get_current_user` |
| `app/routes/auth.py` | Login devuelve permisos; `GET /auth/permisos` |
| `app/main.py` | `init_permisos()` en startup |
| `src/app/util/permisos.ts` | Helpers de localStorage para permisos |
| `src/app/util/rbac.ts` | Configuración de páginas con códigos de permiso |

---

## Tests

```
tests/test_permisos.py          # lógica pura (11 tests)
tests/test_permisos_db.py       # FakeSession, seed y lookup (4 tests)
tests/test_auth_permisos.py     # _autorizar / 403 (4 tests)
tests/test_auth_endpoint_permisos.py  # listar_permisos (2 tests)
```

Ejecutar: `py -m pytest tests/ -q`
