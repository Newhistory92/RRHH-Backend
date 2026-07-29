# Plan: Modelo de PC asignado + scoring persistente (subsistema 7)

**Spec:** `docs/superpowers/specs/2026-07-29-activos-modelo-asignado-design.md`
**Branch:** `activos-modelo-asignado`
**Repos:** Backend_RRHH (backend, tareas 1-3) + RRHH (frontend, tareas 4-6)

## Global Constraints

- SQL 100% parametrizado con `text()` y dict de params — nunca interpolación.
- DDL idempotente: `IF COL_LENGTH(...) IS NULL ALTER TABLE ...` en batch
  separado + commit (SQL Server compila el batch entero).
- RBAC: lecturas `require_any_auth`, escrituras `require_roles(ROLE_ADMIN)`.
- Historial: cada mutación escribe en `ActivoHistorial` dentro de la misma
  transacción, antes del commit.
- CSS semántico: tokens del tema (`text-success`, `bg-error`, `border-border`,
  etc.) — nunca colores raw de Tailwind (`red-500`, `green-600`).
- NO tocar `prisma/schema.prisma` ni `src/app/util/UiRRHH.tsx`.
- `inputCls = 'px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm'`
  es el estilo estándar de inputs en ActivosInventario.

---

## Task 1: Columna modeloId + ensure_tables

**Repo:** Backend_RRHH
**File:** `app/database/activos_modelos.py`

### What to do

1. En `ensure_tables(db)`, después del ALTER de `specsJson`, agregar un nuevo
   bloque idempotente que cree la columna `modeloId INT NULL` en `Activo`:

   ```python
   db.execute(text("IF COL_LENGTH('Activo','modeloId') IS NULL ALTER TABLE Activo ADD modeloId INT NULL;"))
   db.commit()
   ```

   Debe ir en su propio batch + commit (mismo patrón que `specsJson`).

2. Agregar una función `asignar_modelo(db, activo_id, modelo_id)`:
   ```python
   def asignar_modelo(db: Session, activo_id: int, modelo_id: Optional[int]) -> None:
       db.execute(text("UPDATE Activo SET modeloId = :m, updatedAt = :now WHERE id = :id"),
                  {"m": modelo_id, "now": datetime.utcnow(), "id": activo_id})
   ```

3. Agregar una función `score_rapido(db, pc_id)` que retorne `int | None`:
   - Lee el `modeloId` de la PC.
   - Si es None, retorna None.
   - Llama a `evaluar_pc(db, pc_id, modeloId)` y retorna solo el `score`.
   - Se usará en el listado para agregar el score a cada PC.

### Verification

- `py -m py_compile app/database/activos_modelos.py` → exit 0
- Script de prueba: llamar `ensure_tables`, verificar que la columna
  `modeloId` existe en `INFORMATION_SCHEMA.COLUMNS`, llamar
  `asignar_modelo`, verificar el UPDATE, llamar `score_rapido`.

---

## Task 2: _SELECT_ACTIVO + _fila_a_dict + listado con score

**Repo:** Backend_RRHH
**File:** `app/database/activos.py`

### What to do

1. En `_SELECT_ACTIVO`, agregar `a.modeloId` al SELECT y un LEFT JOIN:
   ```sql
   LEFT JOIN ActivoModeloPC m ON a.modeloId = m.id
   ```
   Y seleccionar `m.nombre AS modeloNombre` en la lista de columnas.

   **IMPORTANTE:** El JOIN debe ir después del LEFT JOIN de `pcp` (línea 184
   actual) y antes del `WHERE`. El alias debe ser `m` (no `mod` ni otro).

2. En `_fila_a_dict`, agregar:
   ```python
   "modeloId": r["modeloId"],
   "modeloNombre": r["modeloNombre"],
   ```
   Después de `puedeAlbergarComponentes`.

3. En `listar_activos`, después de construir la lista con `_fila_a_dict`,
   enriquecer las PCs que tienen `modeloId` con su score:
   ```python
   from app.database.activos_modelos import score_rapido
   for item in resultado:
       if item.get("modeloId"):
           item["score"] = score_rapido(db, item["id"])
       else:
           item["score"] = None
   ```

4. En `obtener_activo`, enriquecer el dict con `evaluacion`:
   ```python
   from app.database.activos_modelos import evaluar_pc
   d = _fila_a_dict(r)
   if d.get("modeloId"):
       d["evaluacion"] = evaluar_pc(db, activo_id, d["modeloId"])
   else:
       d["evaluacion"] = None
   return d
   ```

### Verification

- `py -m py_compile app/database/activos.py` → exit 0
- Script: listar activos, verificar que las PCs tienen `modeloId`,
  `modeloNombre`, y `score` en el resultado. Verificar `obtener_activo`
  devuelve `evaluacion` cuando hay modelo asignado.

---

## Task 3: Endpoint PATCH /activos/{activo_id}/modelo

**Repo:** Backend_RRHH
**File:** `app/routes/activos.py`

### What to do

1. Importar `asignar_modelo` desde `app.database.activos_modelos`:
   ```python
   from app.database.activos_modelos import ensure_tables as ensure_tables_modelos, asignar_modelo, evaluar_pc as evaluar_pc_modelos
   ```
   (Ajustar el import existente de `ensure_tables_modelos` para incluir las nuevas funciones.)

2. Agregar endpoint (DESPUÉS de los PATCH existentes, ANTES de DELETE):
   ```python
   @router.patch("/{activo_id}/modelo", dependencies=[Depends(require_admin)])
   def asignar_modelo_pc(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                         current_user: dict = Depends(get_current_user)):
       ensure_tables(db)
       ensure_tables_modelos(db)
       actual = obtener_activo(db, activo_id)
       if not actual:
           raise HTTPException(status_code=404, detail="Activo no encontrado")
       if not actual["puedeAlbergarComponentes"]:
           raise HTTPException(status_code=400, detail="Solo se puede asignar modelo a PCs")

       nuevo_id = data.get("modeloId")
       nuevo_nombre = None
       if nuevo_id is not None:
           from app.database.activos_modelos import obtener_modelo
           modelo = obtener_modelo(db, nuevo_id)
           if not modelo:
               raise HTTPException(status_code=404, detail="Modelo no encontrado")
           nuevo_nombre = modelo["nombre"]

       viejo_nombre = actual.get("modeloNombre")
       if nuevo_id != actual.get("modeloId"):
           registrar_historial(db, activo_id, "cambio_modelo", "modelo",
                               viejo_nombre, nuevo_nombre, current_user.get("employeeId"))

       asignar_modelo(db, activo_id, nuevo_id)
       evaluacion = None
       if nuevo_id:
           evaluacion = evaluar_pc_modelos(db, activo_id, nuevo_id)
       db.commit()
       return {"message": "Modelo asignado" if nuevo_id else "Modelo desasignado",
               "evaluacion": evaluacion}
   ```

3. Importar `registrar_historial` ya está importado en el archivo.

### Verification

- `py -m py_compile app/routes/activos.py` → exit 0
- curl/script: PATCH un modelo a una PC, verificar response con evaluacion.
  PATCH null para desasignar, verificar historial.

---

## Task 4: Interfaces TypeScript

**Repo:** RRHH
**File:** `src/app/Interfas/Interfaces.ts`

### What to do

1. En `ActivoListItem` (línea ~723), agregar después de `puedeAlbergarComponentes`:
   ```typescript
   modeloId: number | null;
   modeloNombre: string | null;
   score: number | null;
   ```

2. En `HistorialItem` — no necesita cambios, `accion` ya es `string`.

### Verification

- `npx tsc --noEmit` en el repo RRHH → sin errores nuevos.

---

## Task 5: Frontend — ficha de PC con modelo persistente

**Repo:** RRHH
**File:** `src/app/screens/ActivosInventario/Screen.tsx`

### What to do

1. **`abrirFicha`** (línea ~183): después de setear `setModeloEvalId('')` y
   `setEvaluacion(null)`, agregar lógica para cargar la evaluación guardada:
   ```typescript
   if (det.modeloId) {
     setModeloEvalId(String(det.modeloId));
     // Si obtener_activo ya devuelve evaluacion, usarla directamente
     if ((det as any).evaluacion) {
       setEvaluacion((det as any).evaluacion);
     }
   } else {
     setModeloEvalId('');
     setEvaluacion(null);
   }
   setErrorEval('');
   ```

   Mejor aún: agregar `evaluacion` al tipo. En el `abrirFicha`:
   ```typescript
   const det = await apiClient.get<ActivoDetalle & { evaluacion?: EvaluacionResultado | null }>(`/activos/${id}`);
   ```

2. **`evaluarContraModelo`**: cambiar para que persista la elección vía PATCH:
   ```typescript
   const evaluarContraModelo = async (pcId: number, modeloId: string) => {
     setModeloEvalId(modeloId);
     setErrorEval('');
     try {
       const mid = modeloId ? Number(modeloId) : null;
       const r = await apiClient.patch<{ message: string; evaluacion: EvaluacionResultado | null }>(
         `/activos/${pcId}/modelo`,
         { modeloId: mid }
       );
       setEvaluacion(r.evaluacion);
       // Actualizar el seleccionado local para reflejar el cambio
       if (seleccionado) {
         setSeleccionado({ ...seleccionado, modeloId: mid, modeloNombre: modelosPC.find(m => m.id === mid)?.nombre || null });
       }
     } catch (e) {
       setEvaluacion(null);
       setErrorEval((e as Error).message);
     }
   };
   ```

3. **Label del dropdown**: cambiar de "Evaluar contra modelo" a
   "Modelo de referencia asignado".

4. **Opción vacía del dropdown**: cambiar de `"— Elegí un modelo —"` a
   `"— Sin modelo asignado —"`.

### Verification

- `npx tsc --noEmit` sin errores.
- En el browser: abrir ficha de PC, elegir modelo → score aparece y persiste
  al cerrar/reabrir la ficha.

---

## Task 6: Frontend — score en listado + historial

**Repo:** RRHH
**File:** `src/app/screens/ActivosInventario/Screen.tsx`

### What to do

1. **Badge de score en el listado**: en la tabla del inventario, dentro de
   cada fila de activo que sea PC (`r.puedeAlbergarComponentes`), mostrar
   un badge con el score:
   - Si `r.score !== null && r.score !== undefined`:
     - `r.score >= 80` → `<span className="text-success font-medium">{r.score}%</span>`
     - `r.score >= 50` → `<span className="text-warning font-medium">{r.score}%</span>`
     - `r.score < 50` → `<span className="text-error font-medium">{r.score}%</span>`
   - Si no tiene modelo: `<span className="text-muted-foreground">—</span>`
   - Para activos que no son PC: no mostrar nada.

   Agregar esto como una columna extra en la tabla o como un badge inline
   junto al nombre de la PC. El approach exacto depende de cómo está
   estructurada la tabla — usar un badge inline junto al nombre es menos
   invasivo que agregar una columna.

2. **Etiqueta de historial**: en `etiquetaHistorial` (línea ~46), agregar
   un case:
   ```typescript
   case 'cambio_modelo':
     return { icono: 'cambio_modelo', texto: `Modelo cambiado: ${h.valorAnterior || 'ninguno'} → ${h.valorNuevo || 'ninguno'}` };
   ```

3. **Refrescar listado**: después de asignar modelo en la ficha y volver
   al listado, el score debe aparecer actualizado. Ya funciona porque
   `cargar()` se llama al cambiar a modo lista.

### Verification

- `npx tsc --noEmit` sin errores.
- En el browser: ver el listado, las PCs con modelo muestran su score
  coloreado. Abrir historial de una PC donde se asignó modelo, verificar
  que aparece el evento.

---

## Task 7: Verificación manual end-to-end

**Repo:** Ambos

### Checklist

1. Reiniciar backend → `modeloId` column creada sin errores.
2. GET /activos → PCs muestran `modeloId: null`, `modeloNombre: null`, `score: null`.
3. PATCH /activos/{pc_id}/modelo con `{ modeloId: 3 }` → response con evaluación.
4. GET /activos/{pc_id} → `modeloId: 3`, `modeloNombre: "pc ADMINISTRATIVA"`,
   `evaluacion` con score calculado.
5. GET /activos → esa PC muestra `score: 25` (o el valor calculado).
6. Frontend listado: la PC muestra badge rojo "25%".
7. Frontend ficha: al abrir la PC, el dropdown ya muestra "pc ADMINISTRATIVA"
   y el score aparece automáticamente sin seleccionar nada.
8. Cambiar modelo en dropdown → persiste, response inmediato con nuevo score.
9. Desasignar modelo (elegir "Sin modelo") → score desaparece.
10. Historial: verificar eventos `cambio_modelo` con antes/después.
11. PATCH modelo en un activo que NO es PC → 400 "Solo se puede asignar modelo a PCs".
