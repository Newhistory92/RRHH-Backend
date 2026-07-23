# Sistema de Activos — Trazabilidad, transferencias y daños (subsistema 4)

## Contexto

Cuarto subsistema del **Sistema Integral de Gestión de Activos Tecnológicos y Patrimoniales**. Construye
sobre los subsistemas 1-3 (config/catálogos, activos base, PCs+componentes — los tres ya mergeados en
`main` de ambos repos). Desde el subsistema 2, cada mutación de un `Activo` escribe una fila en
`ActivoHistorial` (auditoría inmutable) — hoy esa tabla tiene datos reales (85 filas verificadas: `creacion`,
`cambio_estado`, `cambio_responsable`, `modificacion`, `baja`, `instalacion`, `desinstalacion`,
`componente_agregado`, `componente_quitado`, `reemplazo`) pero **no existe ningún endpoint de lectura** —
es puramente de escritura hasta ahora. Este subsistema construye encima: consultas de historial, un flujo
dedicado de "Cambiar Responsable" (transferencia), y gestión de daños con evidencia fotográfica — los tres
puntos que S2 y S3 dejaron explícitamente diferidos a "S4" en sus propios specs.

Orden del sistema completo (7 subsistemas): 1 Config ✅ → 2 Activos base ✅ → 3 PCs+componentes ✅ →
**4 Trazabilidad (este)** → 5 Garantías/vida útil/obsolescencia → 6 Modelos de PC + scoring →
7 Dashboards + búsqueda global.

## Decisiones de diseño (confirmadas con el usuario)

1. **Historial por persona/oficina/departamento = responsable actual, no tenencia histórica.** Filtra los
   activos cuyo responsable ACTUAL es esa persona/oficina/depto, mostrando el historial completo de esos
   activos. No requiere cambios de esquema; no encuentra activos que esa persona tuvo en el pasado pero ya
   no tiene (eso quedaría para un subsistema futuro si se pide, con columnas adicionales en
   `ActivoHistorial` para snapshotear el responsable en cada evento).
2. **Sin pantalla de búsqueda nueva.** El filtro "por persona/oficina/depto" se resuelve agregando un
   filtro más (**Empleado**) a la barra de filtros que ya existe en el listado de Inventario (los filtros
   de departamento/oficina ya existen desde S2). Se hace clic en cualquier fila para ver su ficha con el
   historial completo.
3. **Daños: descripción + foto opcional, cambia el estado, sin tabla nueva.** "Reportar daño" es un
   diálogo con descripción (obligatoria) y foto (opcional, reusa la infraestructura de subida ya existente
   de Portal Institucional — guardado en disco, sin tabla de adjuntos). Al confirmar: cambia el estado del
   activo a "Dañado" y escribe una fila de historial enriquecida (`accion='dano_reportado'`) con la
   descripción y el link a la foto. No hay tabla `ActivoDano` ni estado de resolución del daño (reportado/
   en reparación/resuelto) — la vuelta a servicio usa el "Cambiar estado" que ya existe de S2.

## A. Modelo de datos

**Sin tablas nuevas, sin columnas nuevas.** Todo se apoya en lo que S1-S3 ya crearon:

- **Historial**: pura lectura de `ActivoHistorial` (ya existe). Se agrega una nueva `accion` posible al
  vocabulario que ya escribe la capa de escritura: `'dano_reportado'` (mismo patrón que `'baja'`,
  `'reemplazo'`, etc. — no requiere cambio de esquema, `accion` ya es `NVARCHAR(30)` libre).
- **Transferir (Cambiar Responsable dedicado)**: usa las columnas `responsableTipo`/
  `responsableEmpleadoId`/`responsableOficinaId`/`responsableDepartamentoId` que ya existen en `Activo`
  desde S2 — solo cambia *cómo* se editan (un endpoint/diálogo dedicado en vez de pasar por el form
  completo de edición).
- **Filtro por Empleado**: usa `Activo.responsableEmpleadoId` directo (no la resolución "efectiva" que S2
  ya construyó para depto/oficina — un empleado responsable siempre es directo, nunca necesita resolverse
  a través de una oficina/departamento).
- **Evidencia de daño**: la foto se guarda en disco bajo una carpeta nueva `uploads/activos_danos/`
  (`StaticFiles` ya sirve toda la carpeta `uploads/` genéricamente desde `main.py` — no hace falta tocar el
  mount). La URL resultante se guarda en la propia fila de `ActivoHistorial` (`valorNuevo`), sin tabla de
  adjuntos — coherente con que `Activo.imagenReferencial` (S2) ya es solo una URL de texto.

**Mapeo de columnas de `ActivoHistorial` para `dano_reportado`:**

| Columna | Contenido |
|---|---|
| `accion` | `'dano_reportado'` |
| `campo` | `'dano'` |
| `valorAnterior` | nombre del estado previo (para contexto — "estaba en X") |
| `valorNuevo` | URL de la foto subida, o `NULL` si no se adjuntó foto |
| `observacion` | descripción del daño (texto libre) |

## B. Backend

**Módulo de datos** (`app/database/activos.py`):
- `historial_de_activo(db, activo_id) -> list[dict]`: todas las filas de `ActivoHistorial` de ese activo,
  ordenadas por `createdAt DESC, id DESC` (más recientes primero), con el nombre del usuario resuelto vía
  `LEFT JOIN Employee` sobre `usuarioEmpleadoId`.
- `listar_activos` gana un parámetro más: `empleado_id: Optional[int] = None` → filtra
  `AND a.responsableTipo = 'empleado' AND a.responsableEmpleadoId = :empId`.

**Router** (`app/routes/activos.py`), nuevos endpoints (agregados al final del archivo, no interfieren con
el orden de rutas existente ya que ninguno colisiona con `/{activo_id}`):

| Endpoint | RBAC | Descripción |
|---|---|---|
| `GET /activos/{id}/historial` | `require_any_auth` | Timeline completo del activo (`historial_de_activo`) |
| `PATCH /activos/{id}/responsable` | ADMIN | Reusa `_validar_responsable` (ya existe) para validar tipo+id; si el responsable efectivamente cambia, escribe `cambio_responsable` con el nombre nuevo resuelto vía `_nombre_responsable` (ya existe); actualiza las 4 columnas de responsable + `updatedAt` |
| `POST /activos/{id}/danos` | ADMIN | Multipart (`descripcion: Form`, `foto: File` opcional). Valida `descripcion` no vacía; si hay foto, valida extensión (`jpg/jpeg/png/webp/gif`) y tamaño (≤5 MB) antes de guardar en disco; busca el estado con `codigo='danado'` (400 si no existe); escribe una fila de historial según la tabla de mapeo de la sección A; actualiza `Activo.estadoId` |
| `GET /activos?...&empleadoId=` | `require_any_auth` | Extensión del endpoint ya existente — nuevo filtro opcional |

**Validaciones (400 antes de tocar DB/disco):**
- Foto con extensión no permitida o que excede 5 MB → 400, nada se guarda en disco.
- `descripcion` vacía en "Reportar daño" → 400.
- `PATCH /responsable`: mismas reglas que `_validar_responsable` ya aplica en el resto del módulo (tipo
  fuera de `RESPONSABLE_TIPOS` → 400; id referenciado inexistente → 400).
- Estado "Dañado" no configurado (`codigo='danado'` ausente) → 400 con mensaje claro.
- Activo inexistente en cualquier endpoint → 404.

## C. Frontend

**Ficha del activo** (`screens/ActivosInventario/Screen.tsx`) — dos botones nuevos junto a "Editar"/
"Cambiar estado":

- **"Transferir"** → diálogo liviano: select de tipo (Empleado/Oficina/Departamento, mismo patrón
  `RESP_TIPOS` que `ActivoForm`) + select de destino (reusa `depts`/`empleados` ya cargados en `Screen.tsx`
  para la barra de filtros) + motivo/observación → `PATCH /activos/{id}/responsable`. Al confirmar,
  refresca la ficha.
- **"Reportar daño"** → diálogo: descripción (textarea, obligatoria) + foto opcional
  (`<input type="file" accept="image/*">`) → `POST /activos/{id}/danos` multipart, vía una función nueva
  `reportarDano(activoId, descripcion, foto)` en `src/app/util/uploadClient.ts` (mismo patrón fetch+FormData
  que la ya existente `uploadAttachment`, apuntando a `/activos/{id}/danos` en vez de
  `/publications/attachments`). Al confirmar, refresca la ficha (el estado ya cambió a "Dañado" en el
  backend).

**Nueva sección "Historial"** en la ficha (debajo de "Componentes instalados", visible para cualquier
activo, no solo PCs): timeline de `GET /activos/{id}/historial`. Cada fila se renderiza con un ícono +
etiqueta amigable derivados de `accion`/`campo` (mapeo fijo en el frontend, ej. "Cambio de estado:
{valorAnterior} → {valorNuevo}", "Daño reportado" con link a la foto si `valorNuevo` es una URL), más fecha
y `usuarioNombre`. El backend no resuelve nombres para ids crudos históricos (ver Fuera de alcance) — el
frontend solo pone una etiqueta genérica por tipo de acción.

**Listado principal**: se agrega un filtro **Empleado** a la barra de filtros existente (junto a categoría/
grupo/estado/departamento/oficina), reusando `/rrhh/employees` (ya se consume en `ActivoForm`).

Sin pantallas nuevas, sin cambios de ruteo/RBAC (`rbac.ts`/`page.tsx`/`AppSidebar.tsx` no se tocan) — todo
vive dentro de la pantalla "Inventario" ya existente. Estilo "Orgánico Cálido" (tokens semánticos, dark
mode, responsive), diálogos con el mismo overlay `fixed inset-0 bg-black/50` que los ya existentes.

## Manejo de errores

- Validaciones → 400 con mensaje claro antes de tocar DB/disco; inexistente → 404; escritura sin ser ADMIN
  → 403.
- Foto con extensión inválida o que excede el límite → 400, no se escribe nada en disco (fail fast, antes
  de `os.makedirs`/escritura).
- Frontend: cada diálogo nuevo con su propio estado de error inline (mismo patrón que "Reemplazar"/
  "Agregar componente" de S3), sin `alert()`.

## Fuera de alcance (otros subsistemas o futuro)

- Transferencias masivas (mover N activos a la vez) — se transfiere de a un activo.
- Resolver nombres legibles para los ids crudos ya guardados en `instalacion`/`desinstalacion`/
  `componente_agregado`/`componente_quitado` (quedan con etiqueta genérica por tipo de acción en el
  frontend, no por-id).
- Historial "por persona/oficina/depto" con tenencia pasada (solo responsable actual, ver Decisión 1).
- Estado de resolución del daño (reportado/en reparación/resuelto), costo estimado de reparación,
  aseguradora — subsistema futuro si se pide; hoy "Reportar daño" solo cambia el estado y deja evidencia.
- Garantías, vida útil, obsolescencia — subsistema 5.
- Modelos de PC de referencia + scoring — subsistema 6.
- Dashboards y búsqueda global — subsistema 7.
- RBAC fino por módulo/acción (ej. que un empleado pueda reportar daños solo de sus propios activos) —
  subsistema posterior; por ahora todas las escrituras de este módulo son ADMIN grueso.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/activos.py app/database/activos.py`).
2. Ver el historial de un activo con actividad previa real (de S2/S3) → aparecen todas sus filas, más
   recientes primero, con nombre de usuario resuelto.
3. Transferir un activo a un empleado/oficina/departamento distinto del actual → la ficha refleja el nuevo
   responsable; el historial muestra una fila `cambio_responsable` con el nombre nuevo correctamente
   resuelto (no `null`).
4. Reportar un daño con foto → el estado del activo pasa a "Dañado"; el historial muestra `dano_reportado`
   con la descripción y un link a la foto que efectivamente abre la imagen subida.
5. Reportar un daño sin foto → funciona igual, sin link a foto, sin errores.
6. Intentar reportar un daño con una extensión de archivo no permitida o un archivo demasiado grande → 400
   claro, nada se guarda en disco.
7. Filtrar el listado principal por Empleado → muestra solo los activos cuyo responsable actual es ese
   empleado.
8. RBAC: un no-ADMIN puede ver el historial de un activo pero recibe 403 al intentar transferir o reportar
   un daño.
9. Dark mode y responsive de los dos diálogos nuevos y de la sección "Historial".
