# Mapeo de títulos académicos → profesión (configurable)

## Contexto

`RRHH/src/app/Componentes/CvComponente/HabilidadesTecnicas.tsx` usa un diccionario hardcodeado para traducir el título académico literal de un empleado al nombre de "profesión" que usa la tabla `TechnicalSkill.profession` (texto libre), de modo que se le muestren los tests técnicos correctos:

```ts
const SPECIAL_TITLE_MAPPINGS: Record<string, string> = {
    "Bachiller": "Administración Pública",
    "Bachillerato": "Administración Pública",
    "Administración Pública": "Administración Pública",
};
```

El título académico de un empleado a veces no coincide literalmente con el nombre de la profesión (ej. el título formal es "Bachiller" pero corresponde a la especialización "Administración Pública"). Hoy solo hay un caso cubierto; agregar otro requiere tocar código del frontend y desplegar.

## Decisión

Mover este mapeo a una tabla de base de datos administrable desde la pantalla **TestConfig**, que es donde ya se gestionan las "profesiones" tal como las usa `TechnicalSkill` (también texto libre, vía `/configtest/technical`) — mismo concepto, misma ubicación administrativa.

## Modelo de datos

Tabla nueva `AcademicTitleMapping`:

| Columna | Tipo | Notas |
|---|---|---|
| `id` | int, PK, identity | |
| `tituloAcademico` | nvarchar | título académico literal (ej. "Bachiller") |
| `profession` | nvarchar | valor que debe coincidir con `TechnicalSkill.profession` (ej. "Administración Pública") |
| `activo` | bit, default 1 | soft delete, mismo patrón que `Profession`/`TipoContrato` |
| `createdAt` | datetime, NOT NULL | mismo patrón que las demás tablas nuevas de este backend (ver fix de persistencia del CV) |
| `updatedAt` | datetime, NOT NULL | idem |

**Seed inicial** (migración/script, no endpoint): insertar los 3 mapeos hoy hardcodeados, para no perder comportamiento al desplegar:
- `Bachiller` → `Administración Pública`
- `Bachillerato` → `Administración Pública`
- `Administración Pública` → `Administración Pública`

## Backend

Nuevos endpoints en `app/routes/configtest.py` (mismo router que `/configtest/technical`, mismo patrón de permisos que `professions.py`):

- `GET /configtest/academic-title-mappings` — `require_any_auth`. Devuelve todos los mapeos activos: `{"mappings": [{"id", "tituloAcademico", "profession"}, ...]}`.
- `POST /configtest/academic-title-mappings` — `require_admin`. Crea o actualiza (si viene `id` en el body, UPDATE; si no, INSERT, con chequeo de duplicado por `tituloAcademico` igual que `professions.py`). Requiere `tituloAcademico` y `profession` no vacíos.
- `DELETE /configtest/academic-title-mappings/{mapping_id}` — `require_admin`. Soft delete (`activo = 0`).

Todos los INSERT setean `createdAt`/`updatedAt` con `datetime.utcnow()` explícitamente (no hay default en la base, confirmado por los errores de `IntegrityError` ya resueltos en otras tablas de este mismo backend).

## Frontend

**`HabilidadesTecnicas.tsx`**:
- Se elimina `SPECIAL_TITLE_MAPPINGS`.
- Nuevo `useEffect` (o se extiende `fetchDbSkills`) que hace `GET /configtest/academic-title-mappings` una vez al montar, y arma `Record<string, string>` (`tituloAcademico` → `profession`) en estado local.
- El resto de la lógica de matching (`titlesToMap`, el `.find` sobre `dbSkills`) queda igual, solo cambia el origen del diccionario.
- Mientras el fetch está en curso, el comportamiento es el mismo que hoy si no hay mapeos (usa el título literal sin traducir) — no bloquea el render existente.

**`TestConfig/Screen.tsx`**:
- Nueva sub-sección (tabla simple + form de alta: dos inputs de texto "Título académico" / "Profesión" + botón agregar; botón eliminar por fila), ubicada junto a la gestión de profesiones existente.
- Reusa el patrón visual ya retemado en este screen (tokens `bg-card`, `border-border`, etc.).

## Fuera de alcance

- Unificar `TechnicalSkill.profession` (texto libre) con la tabla `Profession` separada (WIP en `app/routes/professions.py`, pensada para contratos/RRHH) — son conceptos paralelos hoy, no se tocan.
- Cualquier cambio al flujo de validación de habilidades con IA (`TestModal`/`SkillTest`).
- Mejoras de UX del perfil/CV — fuera de alcance, sesión futura separada.

## Testing

- No hay test suite automatizado en este backend ni en el frontend para este flujo — verificación manual:
  1. Como admin, en TestConfig, agregar un mapeo nuevo (ej. "Técnico" → "Sistemas").
  2. Como empleado con título académico "Técnico", abrir el CV — confirmar que ve los tests de la profesión "Sistemas" en Habilidades Técnicas.
  3. Confirmar que los 3 mapeos del seed siguen funcionando igual que el hardcode original (caso "Bachiller").
  4. Eliminar un mapeo desde TestConfig — confirmar que deja de aplicarse (el título vuelve a buscarse literal).
