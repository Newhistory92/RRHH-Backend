# Portal Institucional — Búsqueda avanzada + filtros (subsistema 4)

## Contexto

Cuarto y último subsistema del Portal de Comunicación Institucional. Los subsistemas 1 (núcleo de publicaciones), 2 (Home del empleado) y 3 (editor rich-text + adjuntos) ya están mergeados a `main`.

Este subsistema agrega **filtros y búsqueda** sobre las publicaciones, en las dos pantallas que ya las muestran:

- **Home del empleado** (`src/app/screens/PortalInicio/Screen.tsx`, subsistema 2) — el feed que ven todos los roles ("Novedades y comunicados institucionales").
- **Gestión de publicaciones** (`src/app/screens/GestionPublicaciones/Screen.tsx`, subsistema 3) — la pantalla admin (Admin/RRHH) con la tabla y el crear/editar.

**Nota de alcance:** este subsistema originalmente incluía un dashboard admin con estadísticas (total/activas/archivadas/borradores). Ese dashboard fue **descartado explícitamente por el usuario**: el subsistema queda reducido a filtros + búsqueda, disponibles para todos los roles.

## Decisiones de diseño (confirmadas con el usuario)

1. **Filtros/búsqueda en ambas pantallas**: la Home del empleado (todos los roles) y la de gestión (admin).
2. **Sin estadísticas / dashboard** — descartado explícitamente.
3. **Set de filtros:**
   - Comunes a ambas pantallas: **búsqueda de texto** (sobre título + resumen, no sobre el contenido HTML), **categoría** (las 9), **prioridad** (Baja/Normal/Alta/Urgente).
   - Solo en gestión (admin): **estado** (Borrador/Programada/Publicada/Archivada) y **rango de fechas** (desde/hasta sobre `fechaPublicacion`). El empleado no los necesita: solo ve publicadas.
4. **Filtrado en el backend** (no en el cliente): se agregan query params opcionales a los dos endpoints de lectura ya existentes; el frontend re-consulta al cambiar los filtros. Elegido sobre el filtrado en cliente para que escale a volúmenes mayores.
5. **Sin tablas ni endpoints nuevos**: solo se extienden `GET /publications` y `GET /publications/feed`.

## A. Backend — query params en los dos endpoints

Todo con SQL parametrizado (valores bindeados; la búsqueda de texto usa `LIKE '%' + :q + '%'` con el parámetro bindeado, sin concatenar strings de usuario).

### A.1 `GET /publications` (gestión, `require_rrhh_auth`)

Hoy acepta `categoria` y `estado`. Se agregan query params **opcionales**:

| Param | Efecto SQL / lógica |
|---|---|
| `texto` | `AND (titulo LIKE :q OR resumen LIKE :q)` con `:q = '%' + texto + '%'` |
| `categoria` | `AND categoria = :categoria` (ya existe) |
| `prioridad` | `AND prioridad = :prioridad` |
| `fechaDesde` | `AND fechaPublicacion >= :fechaDesde` |
| `fechaHasta` | `AND fechaPublicacion <= :fechaHasta` |
| `estado` | post-filtro en Python sobre el **estado efectivo calculado** (ya existe; no es columna sino cálculo por fechas) |

Los filtros de columna (`texto`, `categoria`, `prioridad`, fechas) se arman en el `WHERE` SQL de forma dinámica; `estado` permanece como post-filtro en Python igual que hoy. Todos ausentes → devuelve todo (comportamiento actual intacto). Las fechas se parsean con el helper `_parse_dt` ya existente.

### A.2 `GET /publications/feed` (Home, `require_any_auth`, self-or-admin)

Hoy filtra por estado-publicado (activo, `esBorrador=0`, ventana de fechas) + targeting del empleado. Se agregan query params **opcionales**:

| Param | Efecto SQL |
|---|---|
| `texto` | `AND (p.titulo LIKE :q OR p.resumen LIKE :q)` con `:q = '%' + texto + '%'` |
| `categoria` | `AND p.categoria = :categoria` |
| `prioridad` | `AND p.prioridad = :prioridad` |

Sin `estado` ni fechas. Los filtros nuevos son condiciones `AND` **adicionales** sobre el conjunto ya restringido por visibilidad/targeting, así que un empleado nunca puede filtrar hacia una publicación que no le corresponde.

## B. Frontend — pantalla de gestión (admin)

En `GestionPublicaciones/Screen.tsx`, modo lista, arriba de la tabla existente: una **barra de filtros**.

- Input de texto (título/resumen), select Categoría (9 + "Todas"), select Prioridad (4 + "Todas"), select Estado (4 + "Todos"), dos inputs de fecha (desde/hasta), botón "Limpiar filtros".
- Al cambiar cualquier filtro se re-consulta `GET /publications` con los query params: **texto con debounce ~300ms**, selects y fechas al instante.
- Contador "N publicaciones" arriba de la tabla.
- Sin filtros activos → lista completa (igual que hoy).
- El botón "Nueva publicación" y el click-para-editar de cada fila se mantienen intactos.
- Estilo "Orgánico Cálido" (inputs/selects con `border-border`, `bg-background`, `text-foreground`).

## C. Frontend — Home del empleado

En `PortalInicio/Screen.tsx`, arriba del feed: una **barra de filtros** más simple (texto, Categoría, Prioridad, "Limpiar").

**Manejo de datos (dos arrays de estado):**
- **Al montar**: fetch sin filtros a `GET /publications/feed?employeeId=X` → alimenta la vista agrupada por defecto **y** los widgets del sidebar (calendario + próximos eventos).
- **Al aplicar cualquier filtro** (texto con debounce ~300ms, selects al instante): fetch filtrado → alimenta **solo** el contenido principal. Los widgets del sidebar siguen usando el feed completo del montaje (así "Próximos eventos" no se vacía por filtrar por, digamos, categoría = Circular).

**Vista del contenido principal:**
- **Sin filtros activos** → la vista de hoy: banda de urgentes, sección Destacadas, secciones por categoría (agrupado).
- **Con cualquier filtro activo** → **lista plana** de resultados (misma `PublicationCard`), con contador "N resultados" y botón "Limpiar". Agrupar por sección no tiene sentido durante una búsqueda puntual.

El click en una card sigue abriendo `PublicationDetailDialog`. El sidebar (calendario + próximos eventos) queda visible en ambos casos.

## Manejo de errores

- Falla el re-fetch filtrado → estado de error simple en el área de resultados (patrón ya usado en ambas pantallas), sin romper el resto; los filtros quedan para reintentar.
- Búsqueda sin resultados → estado vacío claro ("No se encontraron publicaciones con esos filtros") + botón "Limpiar".
- Race de respuestas (una consulta lenta que vuelve después de otra más nueva) → se descarta la respuesta obsoleta si el filtro ya cambió (patrón de "request id"/flag de vigencia), para no mostrar resultados viejos.
- Caracteres especiales en la búsqueda (`%`, `_`, comillas) → bindeados como parámetro, sin riesgo de inyección; a lo sumo `%`/`_` actúan como comodín de `LIKE`, aceptable.

## Fuera de alcance

- Estadísticas / dashboard admin (total/activas/archivadas/borradores) — descartado explícitamente por el usuario.
- Guardar/compartir búsquedas, historial de búsquedas — no pedido.
- Paginación / scroll infinito — no se agrega ahora (volumen institucional bajo); si crece, se suma después sin cambiar el contrato de la UI.
- Filtrado en el cliente — descartado a favor del backend (decisión tomada).
- Búsqueda sobre el contenido HTML (`contenido`) — solo título + resumen.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/publications.py`).
2. `GET /publications` con cada filtro por separado y combinados (texto, categoría, prioridad, estado, rango de fechas) → resultados correctos; sin filtros → lista completa.
3. `GET /publications/feed` con texto/categoría/prioridad → respeta el targeting (un empleado no ve algo que no le corresponde aunque matchee el texto).
4. Admin: la barra de filtros re-consulta y actualiza la tabla; "Limpiar" restaura; contador correcto; sin resultados muestra estado vacío.
5. Empleado: sin filtros → vista agrupada; con filtro → lista plana; el sidebar (próximos eventos) no se altera al filtrar; el modal de detalle sigue funcionando.
6. Debounce del texto no dispara una consulta por tecla; respuestas obsoletas se descartan.
7. Dark mode y responsive de ambas barras de filtro.
