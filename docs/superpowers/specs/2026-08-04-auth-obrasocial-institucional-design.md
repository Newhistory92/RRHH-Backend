# Autenticación institucional contra ObraSocial — Diseño

**Fecha:** 2026-08-04
**Estado:** Aprobado
**Ramas afectadas:** `main` (backend y frontend)

## Problema

El sistema RRHH tiene que servir a dos escenarios:

1. **Comercial** — se vende a cualquier organización, que registra sus usuarios desde cero.
2. **Institucional** — la institución ya opera un sistema propio (base `ObraSocial`) con
   sus usuarios y contraseñas. Sus empleados no deberían registrarse de nuevo.

Mantener dos ramas divergentes obliga a duplicar cada arreglo. La solución es una sola
base de código con un proveedor de autenticación conmutable por configuración.

## Contexto existente

El backend ya conecta a la base institucional. `app/database/database.py` expone
`SessionLocalObraSocial`, y `app/routes/obrasocial.py` lee `[ObraSocial].[dbo].[UsuarioAcceso]`.

Las dos tablas relevantes de esa base:

- **`Usuario`** — `idUsuario`, `nombreUsuario`, `claveUsuario`, `anulado`, `idPersona`, …
- **`Persona`** — `idPersona`, `nombrePersona`, `apellidoPersona`, `numeroDocPersona`,
  `sexoPersona`, `telefonoPersona`, `emailPersona`, `fechaNacPersona`, `fotoPersona`, …

`anulado = True` significa que la institución le denegó el acceso al sistema.

El puente hacia RRHH:

```
ObraSocial.Usuario.idPersona
    → ObraSocial.Persona.numeroDocPersona   (DNI)
        → RRHH.Employee.dni
```

**Hecho que simplifica todo:** ambos sistemas hashean con bcrypt en el mismo formato
(`$2b$10$…`). El hash se copia tal cual — el usuario nunca resetea su contraseña.

## Arquitectura

Una variable de entorno decide el proveedor:

```
AUTH_PROVIDER=local        # versión comercial (default)
AUTH_PROVIDER=obrasocial   # versión institucional
```

Archivos nuevos, todos en `main`:

```
app/services/auth_providers/
├── __init__.py      get_provider() lee el .env y devuelve la instancia
├── base.py          AuthProvider — protocolo con autenticar(db, usuario, password)
├── local.py         comportamiento actual: valida bcrypt contra [User]
└── obrasocial.py    flujo híbrido con provisioning on-demand
```

`app/routes/auth.py` delega en `get_provider().autenticar(...)` y sigue emitiendo el JWT
como hoy. El middleware de roles, la blacklist de tokens y el resto del sistema no cambian.

### Columna nueva

`[User].origen NVARCHAR(20) NOT NULL DEFAULT 'local'`

Distingue los usuarios provisionados desde ObraSocial de los creados a mano en RRHH.
Sin esta columna, un admin local que no existe en ObraSocial quedaría bloqueado por la
verificación de `anulado`.

## Flujo de login (`AUTH_PROVIDER=obrasocial`)

### Camino 1 — usuario local puro (`origen = 'local'`)

Es el admin que RRHH creó a mano. Valida bcrypt contra `[User].password` y emite el JWT.
ObraSocial no se consulta.

### Camino 2 — usuario ya provisionado (`origen = 'obrasocial'`)

1. Consulta `ObraSocial.Usuario` por `nombreUsuario`.
2. Si `anulado = True` → **403** "Acceso denegado por la institución".
3. Si `claveUsuario` difiere del hash local → actualiza el hash local. El usuario cambió
   su clave en ObraSocial y la sincronización sale gratis: la query ya se hizo en el paso 1.
4. Valida bcrypt contra el hash local → emite el JWT.

### Camino 3 — primer login (no existe en `[User]`)

1. Busca `ObraSocial.Usuario` por `nombreUsuario`. Si no está → **401**.
2. Si `anulado = True` → **403**.
3. Valida bcrypt contra `claveUsuario`. Si falla → **401**.
4. Sigue `idPersona` → `Persona`.
5. Busca `Employee` por `dni = numeroDocPersona`:
   - Existe → lo vincula.
   - No existe → crea un `Employee` mínimo desde `Persona`.
6. Crea `[User]` con el hash copiado, `roleId = 2` (USER), `employeeId`, `origen = 'obrasocial'`.
7. Emite el JWT.

### Nota sobre disponibilidad

`ObraSocial` y la base de RRHH viven en el mismo servidor. Si una cae, cae la otra y no hay
login posible por ningún camino. No se implementa ningún fallback ni degradación: sería
código muerto.

## Mapeo `Persona` → `Employee`

| `Employee`  | `Persona`                              |
|-------------|----------------------------------------|
| `dni`       | `numeroDocPersona`                     |
| `name`      | `nombrePersona` + `" "` + `apellidoPersona` |
| `email`     | `emailPersona`                         |
| `gender`    | `sexoPersona`                          |
| `phone`     | `telefonoPersona`                      |
| `birthDate` | `fechaNacPersona`                      |
| `photo`     | `fotoPersona`                          |

El `Employee` queda sin departamento, oficina, puesto ni horario — eso lo completa RRHH.
Son identificables por `[User].origen = 'obrasocial'` con `departmentId` nulo.

## Importación proactiva desde RRHH

El provisioning on-demand deja un hueco: RRHH no puede preparar a nadie porque el
`Employee` no existe hasta que la persona entra por primera vez. Un segundo camino de
entrada lo cubre.

### `GET /obrasocial/usuarios`

Reemplaza el `SELECT *` crudo actual por un join con `Persona` que agrega el estado
de vinculación:

```json
{
  "usuarios": [
    {
      "idUsuario": "1915881e-…",
      "nombreUsuario": "EmilianoRojo",
      "anulado": false,
      "nombre": "Emiliano",
      "apellido": "Rojo",
      "dni": "35123456",
      "email": "erojo@institucion.gob.ar",
      "telefono": "3794123456",
      "vinculado": true,
      "employeeId": 264
    }
  ]
}
```

`vinculado` indica si ya existe un `Employee` con ese DNI.

### `POST /obrasocial/importar`

Recibe `{ "idUsuarios": ["1915881e-…", "…"] }`. Para cada uno ejecuta lo mismo que el
camino 3 pero sin validar contraseña: crea el `Employee` desde `Persona` y el `[User]`
con el hash copiado, `roleId = 2` y `origen = 'obrasocial'`.

Cada elemento se resuelve por separado según lo que ya exista:

- Ni `Employee` ni `[User]` → crea ambos. Cuenta como `importado`.
- `Employee` existe (mismo DNI) pero no hay `[User]` → crea solo el `[User]` y lo vincula
  al `Employee` existente. Cuenta como `importado`.
- `[User]` ya existe → no toca nada. Cuenta como `ya_existian`.

Devuelve `{ importados, ya_existian, errores: [{idUsuario, motivo}] }`. Un elemento que
falla no aborta el lote: se registra en `errores` y el resto continúa.

Requiere rol ADMIN.

### Convergencia

Los dos caminos llegan al mismo `Employee` vía DNI, así que no se pisan. Si RRHH ya
importó a alguien, su primer login entra por el camino 2 y encuentra todo hecho. El
camino 3 queda como red de seguridad para quien RRHH no importó.

## Casos borde

Los códigos de estado aplican al login. En la importación el mismo caso no corta el lote:
se registra en `errores` con el mismo motivo y el proceso sigue con el resto.

| Caso | Comportamiento |
|------|----------------|
| `numeroDocPersona` nulo o vacío | **400** con mensaje explícito. El DNI es la clave del vínculo; sin él no se puede crear ni encontrar el `Employee`. RRHH debe completar la persona en ObraSocial. |
| `emailPersona` nulo o duplicado | Se inserta `{nombreUsuario}@sin-email.local`. Determinístico, no resuelve DNS, y queda visible para que RRHH lo corrija. |
| DNI ya vinculado a otro `[User]` | **409** y log para revisión manual. Dos usuarios ObraSocial apuntando al mismo `Employee` es un error de datos, no algo a resolver automáticamente. |
| `nombreUsuario` existe en `[User]` con `origen = 'local'` | Camino 1. Nunca se consulta ObraSocial para ese usuario. |

## Frontend

### Tab nuevo en `screens/Admin/Screen.tsx`

La pantalla Admin ya tiene tabs (`Usuarios Activos`, `Inactivos`, `Roles`, `Perfiles`) y
crea empleados desde usuarios vía `POST /users/employee`. Se agrega **"Usuarios ObraSocial"**:
lista el join `Usuario ⋈ Persona` con nombre, DNI, email, estado `anulado` y `vinculado`,
con selección múltiple y un botón de importar.

Una vez importados aparecen en "Usuarios Activos", donde el flujo existente ya permite
cambiarles el rol. Nada de eso se duplica.

### `GET /auth/config`

Devuelve `{ "authProvider": "local" | "obrasocial" }`. Es un endpoint **público** — se
consulta antes de cualquier login y no expone nada sensible: solo qué modo de
autenticación está activo. El tab se renderiza solo si vale `'obrasocial'`. En la versión
comercial el flag es `'local'`, el tab no existe, y la pantalla Admin se ve exactamente
como hoy.

### Pantalla de login

No cambia. Solo aparecen mensajes de error nuevos, que ya se renderizan desde `detail`.

## Testing

**Funciones puras** — tests unitarios directos:

- `persona_a_employee(persona) -> dict` — el mapeo de la tabla de arriba, incluido el
  fallback de email.
- `get_provider(valor_env) -> AuthProvider` — selección de proveedor, incluido el default
  y un valor inválido.

**Flujo de login** — con una sesión ObraSocial falsa que devuelve filas armadas, sin tocar
bases reales. Cubre los tres caminos y cada caso borde de la tabla.

**Importación** — mismo enfoque: lote con un elemento válido, uno sin DNI y uno duplicado,
verificando que el resumen refleje los tres resultados y que el lote no aborte.

## Fuera de alcance

La versión SaaS multi-tenant (aislamiento de datos por organización, registro de
organizaciones, facturación) es un proyecto aparte con su propio spec. Este diseño solo
prepara el terreno dejando `main` limpia y conmutable.
