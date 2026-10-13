# Alerta de recálculos con errores — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un empleado que falla en el recálculo masivo deje de quedar sin asistencia en silencio: el tablero lo muestra.

**Architecture:** El dato ya existe —`RecalculoLog.errores` lo guarda desde siempre— y nadie lo lee. Una función nueva en la capa de auditoría toma la última corrida masiva terminada, parsea su JSON de errores y le pega el nombre de cada empleado; un endpoint la expone, y el tablero dibuja un panel plegable hermano del de "IDs del reloj sin vincular". Sin tablas, columnas ni estados nuevos: el panel se apaga solo cuando una corrida posterior sale limpia.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15 (App Router), React, Tailwind con los tokens del proyecto.

## Global Constraints

- **Dos repos.** Backend: `C:\Users\Emiliano\Documents\Backend_RRHH` (Task 1). Frontend: `C:\Users\Emiliano\Documents\RRHH` (Task 2). Los commits van en el repo que corresponde, nunca cruzados.
- **Solo las corridas masivas cuentan:** los orígenes `nocturno`, `manual` y `arranque`. Son los tres con los que se registra `recalcular_todos`, la única función que barre toda la nómina. Los orígenes `cupo_permiso` y `extension_tolerancia` son barridos parciales y se ignoran.
- **Solo corridas terminadas:** `finalizadoAt IS NOT NULL`. Una corrida en curso todavía no se sabe cómo terminó.
- **Sin errores, sin panel:** si la última masiva no dejó errores, la función devuelve `None` y el frontend no dibuja nada. Así el panel se apaga solo.
- **El texto técnico de la excepción se muestra tal cual.** Es lo que permite diagnosticar; no se reemplaza por un mensaje amable.
- **Un registro de auditoría corrupto no puede tumbar la pantalla:** si `errores` trae JSON malformado, se devuelve el texto crudo como una entrada sola, nunca una excepción.
- **Nada de estado nuevo:** sin tablas, sin columnas, sin "marcar como visto", sin botón de reintentar (lo cubre "Recalcular todo"), sin notificaciones.
- Backend: `"./venv/Scripts/python.exe" -m pytest` desde el repo. Los 4 `tests/test_chat_*.py` fallan al importar por falta de `google-genai`: es preexistente y ajeno, se excluyen con `--ignore`. Comentarios Python **sin tildes**.
- Frontend: **sin runner de tests.** Verificación `npx tsc --noEmit -p tsconfig.json`, criterio no agregar errores nuevos. El baseline es **27**; contalo con `grep -c "error TS"`, nunca por líneas de salida. Comentarios **con tildes**.
- Commits en español, estilo del repo (`feat/fix/docs`), con línea en blanco y la línea `Co-Authored-By` del entorno.

---

## Estructura de archivos

### Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/database/asistencia_auditoria.py` | **Modificar.** Suma `errores_del_ultimo_barrido`, al lado de `ultimos_recalculos`, que es su vecina natural. |
| `app/routes/asistencia.py` | **Modificar.** Suma `GET /asistencia/recalculos/errores`, calcado de `GET /asistencia/biometricos-huerfanos`. |
| `tests/test_errores_de_recalculo.py` | **Nuevo.** La regla de qué corrida se mira, el parseo y los bordes. |

### Frontend (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` | **Modificar.** El panel plegable, hermano del de huérfanos. |

**Orden:** backend primero (Task 1), porque el frontend consume su endpoint.

---

## Task 1: La consulta y el endpoint

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/asistencia_auditoria.py` (agregar después de `ultimos_recalculos`)
- Modify: `app/routes/asistencia.py` (el import de `asistencia_auditoria` y un endpoint nuevo después de `get_biometricos_huerfanos`)
- Test: `tests/test_errores_de_recalculo.py` (nuevo)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `errores_del_ultimo_barrido(db: Session) -> dict | None`, con la forma:
    ```python
    {"id": int, "origen": str, "finalizadoAt": datetime | None,
     "procesados": int,
     "errores": [{"employeeId": int | None, "nombre": str | None, "error": str}]}
    ```
  - `GET /asistencia/recalculos/errores` → `{"ultimoBarrido": {...} | None}`, que consume la Task 2. En el JSON, `finalizadoAt` va como string ISO o `null`.

**Contexto que importa:** `json` ya está importado en `asistencia_auditoria.py` (lo usa `cerrar_recalculo`, que es quien escribe el campo con `json.dumps`). La columna de nombre en `Employee` es `name`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_errores_de_recalculo.py`:

```python
"""
Los errores del ultimo barrido completo, para que dejen de ser invisibles.

El recalculo masivo esta hecho a proposito para que un empleado que falla no
aborte el resto: se registra en RecalculoLog.errores y se sigue. Correcto
-un legajo roto no puede dejar sin asistencia a toda la planta- pero sin nadie
que lea ese registro, el empleado queda sin calcular indefinidamente y en
silencio. Paso de verdad: cuatro corridas nocturnas seguidas guardaron el mismo
TypeError y se descubrio recien cuando el usuario miro la pantalla.
"""

from datetime import datetime

from app.database.asistencia_auditoria import errores_del_ultimo_barrido
from tests.fakes import FakeSession

LIMPIA = {"id": 110, "origen": "nocturno", "procesados": 5,
          "errores": None, "finalizadoAt": datetime(2026, 10, 14, 3, 0)}
CON_ERROR = {
    "id": 109, "origen": "manual", "procesados": 4,
    "errores": '[{"employeeId": 8, "error": "TypeError: no se puede comparar"}]',
    "finalizadoAt": datetime(2026, 10, 13, 7, 51),
}


def test_sin_errores_no_hay_nada_que_mostrar():
    """La ultima masiva salio limpia: el panel no tiene que aparecer."""
    db = FakeSession({"origen IN": [LIMPIA]})
    assert errores_del_ultimo_barrido(db) is None


def test_sin_ninguna_corrida_registrada_tampoco():
    """Base recien instalada: no hay de que avisar."""
    db = FakeSession({"origen IN": []})
    assert errores_del_ultimo_barrido(db) is None


def test_los_errores_se_parsean_y_traen_el_nombre():
    db = FakeSession({
        "origen IN": [CON_ERROR],
        "name FROM Employee": [{"id": 8, "name": "Emiliano Rojo"}],
    })
    r = errores_del_ultimo_barrido(db)
    assert r["id"] == 109
    assert r["origen"] == "manual"
    assert r["procesados"] == 4
    assert r["errores"] == [{
        "employeeId": 8, "nombre": "Emiliano Rojo",
        "error": "TypeError: no se puede comparar",
    }]


def test_solo_mira_las_corridas_masivas_y_terminadas():
    """
    La regla que define la feature. Se afirma sobre el SQL y no sobre el
    resultado porque FakeSession devuelve lo que se le pida: lo unico que
    prueba que los barridos parciales quedan afuera es el filtro mismo.
    """
    db = FakeSession({"origen IN": []})
    errores_del_ultimo_barrido(db)
    sql = db.ejecutadas[0][0]
    assert "'nocturno'" in sql and "'manual'" in sql and "'arranque'" in sql
    assert "cupo_permiso" not in sql and "extension_tolerancia" not in sql
    assert "finalizadoAt IS NOT NULL" in sql


def test_un_json_malformado_no_tumba_la_pantalla():
    """
    La pantalla existe justamente para mostrar fallas: no puede fallar ella
    misma porque el registro de auditoria quedo corrupto.
    """
    db = FakeSession({"origen IN": [{**CON_ERROR, "errores": "esto no es json"}]})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"] == [
        {"employeeId": None, "nombre": None, "error": "esto no es json"},
    ]


def test_un_empleado_sin_nombre_se_muestra_igual():
    """Legajo borrado de la base: se muestra el numero pelado, no se oculta."""
    db = FakeSession({"origen IN": [CON_ERROR], "name FROM Employee": []})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"][0]["employeeId"] == 8
    assert r["errores"][0]["nombre"] is None


def test_una_entrada_sin_employeeId_se_muestra_igual():
    """Un error de la corrida entera, no atribuible a un empleado."""
    db = FakeSession({"origen IN": [
        {**CON_ERROR, "errores": '[{"error": "se cayo la conexion"}]'},
    ]})
    r = errores_del_ultimo_barrido(db)
    assert r["errores"] == [
        {"employeeId": None, "nombre": None, "error": "se cayo la conexion"},
    ]


def test_sin_employeeIds_no_consulta_nombres():
    """Una vuelta a la base de mas cuando no hay a quien buscarle el nombre."""
    db = FakeSession({"origen IN": [
        {**CON_ERROR, "errores": '[{"error": "se cayo la conexion"}]'},
    ]})
    errores_del_ultimo_barrido(db)
    assert all("FROM Employee" not in sql for sql, _ in db.ejecutadas)
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_errores_de_recalculo.py -v
```

Esperado: FALLA en el import con `ImportError: cannot import name 'errores_del_ultimo_barrido'`.

- [ ] **Step 3: Escribir la función**

En `app/database/asistencia_auditoria.py`, agregar al final del archivo, después de `ultimos_recalculos`:

```python
# Los tres origenes con los que se registra recalcular_todos, que es la unica
# funcion que barre toda la nomina. cupo_permiso y extension_tolerancia son
# barridos parciales y quedan afuera a proposito: los dos filtran sobre la
# misma nomina que el nocturno recorre entera cada noche, asi que un empleado
# que falle ahi vuelve a fallar en el nocturno siguiente, dentro de las 24 hs.
ORIGENES_MASIVOS = ("nocturno", "manual", "arranque")


def errores_del_ultimo_barrido(db: Session) -> Optional[dict]:
    """
    Los errores que dejo la ultima corrida masiva terminada, o None.

    El recalculo masivo registra al empleado que falla y sigue, para que un
    legajo roto no deje sin asistencia a toda la planta. El precio es que el
    fallo queda guardado y nadie lo mira: paso de verdad, cuatro corridas
    nocturnas seguidas con el mismo TypeError. Esta funcion es la que lo saca
    a la superficie.

    Devuelve None cuando la ultima masiva salio limpia, asi el aviso se apaga
    solo en cuanto el problema se corrige, sin que nadie marque nada.
    """
    fila = db.execute(text(f"""
        SELECT TOP 1 id, origen, procesados, errores, finalizadoAt
        FROM RecalculoLog
        WHERE origen IN ({", ".join(f"'{o}'" for o in ORIGENES_MASIVOS)})
          AND finalizadoAt IS NOT NULL
        ORDER BY id DESC
    """)).mappings().first()
    if fila is None or not fila["errores"]:
        return None

    crudos = _parsear_errores(fila["errores"])
    nombres = _nombres_de(db, [e["employeeId"] for e in crudos
                              if e["employeeId"] is not None])
    return {
        "id": int(fila["id"]),
        "origen": fila["origen"],
        "finalizadoAt": fila["finalizadoAt"],
        "procesados": int(fila["procesados"] or 0),
        "errores": [{**e, "nombre": nombres.get(e["employeeId"])}
                    for e in crudos],
    }


def _parsear_errores(crudo: str) -> list[dict]:
    """
    El JSON que escribio cerrar_recalculo, normalizado.

    Si el texto no es JSON valido se devuelve tal cual como una sola entrada:
    esta pantalla existe para mostrar fallas y no puede fallar ella misma
    porque el registro de auditoria quedo corrupto.
    """
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        return [{"employeeId": None, "error": str(crudo)}]
    if not isinstance(datos, list):
        return [{"employeeId": None, "error": str(crudo)}]
    return [{"employeeId": d.get("employeeId"), "error": str(d.get("error"))}
            for d in datos if isinstance(d, dict)]


def _nombres_de(db: Session, employee_ids: list) -> dict:
    """Los nombres de esos legajos, en una sola consulta."""
    ids = {int(i) for i in employee_ids}
    if not ids:
        return {}
    filas = db.execute(text(
        "SELECT id, name FROM Employee WHERE id IN (%s)"
        % ", ".join(str(i) for i in sorted(ids))
    )).mappings().all()
    return {int(f["id"]): f["name"] for f in filas}
```

Si `Optional` no está importado en ese archivo, agregarlo: `from typing import Optional`.

**Sobre el `IN` armado por concatenación:** los ids no vienen del cliente, salen de un JSON que escribió el propio backend, y se fuerzan a `int` antes de concatenar, así que no hay superficie de inyección. Es además el patrón que ya usa el repo para listas de ids.

- [ ] **Step 4: Correr los tests**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_errores_de_recalculo.py -v
```

Esperado: PASS los 8.

- [ ] **Step 5: Agregar el endpoint**

En `app/routes/asistencia.py`, sumar la función al import que ya existe:

```python
from app.database.asistencia_auditoria import (
    borrar_correccion, errores_del_ultimo_barrido, incidencias_abiertas,
    ultimos_recalculos, upsert_correccion,
)
```

Y agregar el endpoint inmediatamente después de `get_biometricos_huerfanos`:

```python
@router.get("/recalculos/errores", dependencies=[GESTIONAR_ASISTENCIA])
def get_errores_de_recalculo(db: Session = Depends(get_db)):
    """
    Los empleados que la ultima corrida masiva no pudo calcular.

    Devuelve ultimoBarrido en null cuando la ultima salio limpia: el tablero
    usa eso para no dibujar el panel.
    """
    ensure_tables(db)
    barrido = errores_del_ultimo_barrido(db)
    if barrido is None:
        return {"ultimoBarrido": None}
    return {"ultimoBarrido": {
        **barrido,
        "finalizadoAt": (barrido["finalizadoAt"].isoformat()
                         if barrido["finalizadoAt"] else None),
    }}
```

- [ ] **Step 6: Verificar que la ruta quedó registrada**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -c "from app.main import app; print([r.path for r in app.routes if 'recalculos' in r.path])"
```

Esperado: incluye `/asistencia/recalculos/errores` además de `/asistencia/recalculos`.

- [ ] **Step 7: Verificar contra la base real**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && PYTHONPATH="C:/Users/Emiliano/Documents/Backend_RRHH" "./venv/Scripts/python.exe" -c "from app.database.database import SessionLocal; from app.database.asistencia_auditoria import errores_del_ultimo_barrido; db=SessionLocal(); print(errores_del_ultimo_barrido(db)); db.close()"
```

Esperado: **`None`**. En esta base la última corrida masiva salió limpia (5 procesados, 0 errores) pero el historial todavía tiene las corridas fallidas del 9 al 13 de octubre. Que devuelva `None` confirma de una sola vez las dos cosas: que mira la última y no el historial, y que el autoapagado funciona.

- [ ] **Step 8: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/asistencia_auditoria.py app/routes/asistencia.py tests/test_errores_de_recalculo.py
git commit -m "$(cat <<'EOF'
feat(asistencia): exponer los errores de la ultima corrida masiva

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: El panel en el tablero

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/Componentes/Asistencia/AsistenciaTablero.tsx`

**Interfaces:**
- Consumes: `GET /asistencia/recalculos/errores` → `{"ultimoBarrido": {id, origen, finalizadoAt, procesados, errores: [{employeeId, nombre, error}]} | null}`, de la Task 1.
- Produces: nada.

**Contexto que importa:** `lanzarRecalculo` termina con `await cargar()`, así que poniendo el fetch dentro de `cargar()` el refresco posterior a "Recalcular todo" sale gratis, sin tocar esa función.

- [ ] **Step 1: Agregar la interfaz y el estado**

En `src/app/Componentes/Asistencia/AsistenciaTablero.tsx`, junto a la interfaz `BiometricoHuerfano` que ya existe, agregar:

```tsx
interface ErrorDeRecalculo {
  employeeId: number | null;
  nombre: string | null;
  error: string;
}

interface BarridoConErrores {
  id: number;
  origen: string;
  finalizadoAt: string | null;
  procesados: number;
  errores: ErrorDeRecalculo[];
}
```

Y junto a los demás `useState` del componente:

```tsx
  const [barridoFallido, setBarridoFallido] = useState<BarridoConErrores | null>(null);
  const [erroresAbierto, setErroresAbierto] = useState(false);
```

- [ ] **Step 2: Pedirlo junto al resto**

En `cargar()`, sumar la llamada al `Promise.all` que ya existe y guardar el resultado:

```tsx
      const [t, i, h, a, e] = await Promise.all([
        apiClient.get<{ empleados: TableroFila[] }>(`/asistencia/tablero?desde=${desdeTablero}&hasta=${hastaTablero}`),
        apiClient.get<{ jornadas: JornadaIncompleta[] }>("/asistencia/incompletas"),
        apiClient.get<{ huerfanos: BiometricoHuerfano[] }>("/asistencia/biometricos-huerfanos"),
        apiClient.get<{ empleados: AlertaTolerancia[]; diasRachaAlerta: number }>(`/asistencia/alertas-tolerancia?desde=${desdeTablero}&hasta=${hastaTablero}`),
        apiClient.get<{ ultimoBarrido: BarridoConErrores | null }>("/asistencia/recalculos/errores"),
      ]);
      setFilas(t.empleados);
      setIncompletas(i.jornadas);
      setHuerfanos(h.huerfanos);
      setAlertas(a.empleados);
      setDiasRachaAlerta(a.diasRachaAlerta);
      setBarridoFallido(e.ultimoBarrido);
```

- [ ] **Step 3: Dibujar el panel**

En el bloque `{tab === "saldo" && (`, **arriba** del panel de "IDs del reloj sin vincular" —un empleado sin calcular es más urgente que un ID sin vincular— agregar:

```tsx
      {/* ── Empleados que el último recálculo no pudo calcular ───── */}
      {barridoFallido && (
        <div className="mb-8 bg-card rounded-lg shadow-sm border border-error overflow-hidden">
          <button
            type="button"
            onClick={() => setErroresAbierto((a) => !a)}
            className="w-full flex items-center justify-between gap-2 p-4 text-left hover:bg-surface-muted transition-colors"
            aria-expanded={erroresAbierto}
          >
            <h2 className="font-heading text-lg text-foreground flex items-center gap-2">
              <i className="pi pi-times-circle text-error" />
              Empleados que no se pudieron calcular ({barridoFallido.errores.length})
            </h2>
            <i className={`pi ${erroresAbierto ? "pi-chevron-up" : "pi-chevron-down"} text-muted-foreground`} />
          </button>

          {erroresAbierto && (
            <div className="px-4 pb-4">
              <p className="text-sm text-muted-foreground mb-4">
                La asistencia de estas personas quedó sin actualizar: el último
                recálculo falló al procesarlas y siguió con el resto. Una vez
                corregida la causa, &quot;Recalcular todo&quot; las vuelve a
                procesar y este aviso desaparece solo.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-muted-foreground border-b border-border">
                      <th className="py-2 pr-4">Legajo</th>
                      <th className="py-2 pr-4">Empleado</th>
                      <th className="py-2">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {barridoFallido.errores.map((e, i) => (
                      <tr key={`${e.employeeId ?? "sin-legajo"}-${i}`} className="border-b border-border last:border-0">
                        <td className="py-2 pr-4 font-mono font-semibold text-error">
                          {e.employeeId ?? "—"}
                        </td>
                        <td className="py-2 pr-4">{e.nombre ?? "—"}</td>
                        <td className="py-2 font-mono text-xs text-muted-foreground break-all">
                          {e.error}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground mt-3">
                Corrida #{barridoFallido.id} ({barridoFallido.origen})
                {barridoFallido.finalizadoAt &&
                  ` · ${barridoFallido.finalizadoAt.slice(0, 16).replace("T", " ")}`}
                {" · "}{barridoFallido.procesados} empleados procesados bien
              </p>
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 4: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -i "AsistenciaTablero"
```

Esperado: sin salida.

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`. **Contar así y no por líneas de salida**: tsc imprime contexto multilínea por error.

- [ ] **Step 5: Verificar en el navegador**

Con el backend y `npm run dev` corriendo, entrando con un usuario con `asistencia.gestionar`:

1. Asistencia → **no** aparece ningún panel de errores. Es lo correcto: la última corrida masiva de esta base salió limpia.
2. Para ver el panel encendido, forzar un error en una corrida:
   ```bash
   cd "C:/Users/Emiliano/Documents/Backend_RRHH" && PYTHONPATH="C:/Users/Emiliano/Documents/Backend_RRHH" "./venv/Scripts/python.exe" -c "
   from app.database.database import SessionLocal
   from app.database.asistencia_auditoria import abrir_recalculo, cerrar_recalculo
   from datetime import date
   db=SessionLocal()
   lid=abrir_recalculo(db,'manual',None,None,date(2026,1,1),date(2026,12,31))
   cerrar_recalculo(db,lid,4,193,[{'employeeId':8,'error':'TypeError de prueba'}])
   print('corrida de prueba',lid)
   db.close()"
   ```
3. Recargar Asistencia: aparece el panel rojo "Empleados que no se pudieron calcular (1)". Abrirlo: muestra legajo 8, el nombre real del empleado y el texto del error, más el pie con el número de corrida y la fecha.
4. Apretar "Recalcular todo" y esperar a que termine: el panel **desaparece solo**, porque la corrida nueva sale limpia. Eso es la regla de autoapagado funcionando de punta a punta.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Componentes/Asistencia/AsistenciaTablero.tsx
git commit -m "$(cat <<'EOF'
feat(asistencia): panel con los empleados que el recalculo no pudo procesar

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Autorrevisión del plan

**Cobertura del spec.** Cada unidad tiene tarea: `errores_del_ultimo_barrido` con la regla de los tres orígenes masivos y `finalizadoAt IS NOT NULL` (T1 Step 3, con un test que afirma sobre el SQL porque es lo único que prueba que los parciales quedan afuera); `None` cuando la última salió limpia, que es el autoapagado (T1); el parseo del JSON con el borde de malformado (T1); el nombre pegado en una sola consulta, con el borde de empleado inexistente y el de entrada sin `employeeId` (T1); el endpoint bajo `asistencia.gestionar` calcado del de huérfanos (T1 Step 5); el panel plegable con legajo, nombre y texto técnico (T2 Step 3); el refresco tras "Recalcular todo" (T2 Step 2, gratis porque `lanzarRecalculo` ya llama a `cargar()`).

**Un test que el spec no pedía y agregué.** `test_sin_employeeIds_no_consulta_nombres`: si todos los errores vienen sin legajo, no tiene sentido ir a la base a buscar nombres. Es la misma clase de vuelta al pedo que ya se corrigió una vez en este proyecto (la consulta de consumo inicial que se hacía aunque el resultado se descartara).

**Dónde va el panel, y por qué ahí.** Arriba del de huérfanos, no abajo: un empleado cuya asistencia quedó sin calcular es un problema más urgente que un ID de reloj sin vincular, y el orden visual tiene que decir eso. Usa `border-error` e ícono `pi-times-circle`, contra el `border-warning` y `pi-exclamation-triangle` del de huérfanos, para que la diferencia de severidad se lea sin texto.

**La verificación que vale más que los tests.** El Step 7 de la T1 y el Step 5 de la T2 se apoyan en un hecho de esta base concreta: el historial tiene las corridas fallidas del 9 al 13 de octubre y encima de ellas una corrida limpia. Que el panel **no** aparezca es la prueba de que la consulta mira la última y no el historial. El paso 2 del Step 5 inyecta una corrida fallida de prueba para ver el panel encendido, y el paso 4 lo apaga con un recálculo real: el ciclo completo verificado contra el sistema de verdad, no contra `FakeSession`.

**Consistencia de nombres.** `errores_del_ultimo_barrido` se define en T1 y se consume con ese nombre en el endpoint. Las claves de la respuesta (`ultimoBarrido`, `id`, `origen`, `finalizadoAt`, `procesados`, `errores`, y dentro `employeeId`, `nombre`, `error`) se declaran en el bloque Interfaces de T1 y la interfaz `BarridoConErrores` de T2 las repite una a una, con `finalizadoAt` como `string | null` porque el endpoint lo serializa con `.isoformat()`.
