# Bloqueo de solicitudes concurrentes + calendario compacto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir que un empleado cree una nueva solicitud de licencia mientras ya tiene una pendiente de aprobación (de cualquier tipo), y achicar el calendario de selección de fechas a un solo mes visible.

**Architecture:** Dos piezas independientes sin código compartido. (1) Backend: validación nueva en `POST /licenses/request` + frontend que deshabilita el botón "Nueva Solicitud" cuando ya hay una pendiente (defensa en profundidad: UI + backend). (2) Frontend puro: cambiar `numberOfMonths` del calendario de PrimeReact de `2` (desktop) a `1` siempre.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL) (backend); Next.js, TypeScript, PrimeReact, `apiClient` (frontend).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-license-request-lock-and-calendar-ux-design.md`
- El bloqueo es global: una sola solicitud pendiente (de **cualquier tipo** de licencia) impide crear cualquier otra, sin importar el tipo de la nueva.
- Estados que cuentan como "pendiente": `'Pendiente'` y `'Pendiente Siguiente Aprobación'` (los únicos 2 valores no-terminales de `LicenseStatus`).
- El backend valida siempre (no confiar solo en el frontend) — la validación de UI es solo para evitar el viaje innecesario al usuario, no reemplaza la del backend.
- No se toca el flujo de aprobación/derivación de supervisores, ni se agrega opción de cancelar una solicitud pendiente — fuera de alcance.
- No hay test suite automatizado en ninguno de los dos repos — verificación vía `python -c "import ..."`, `npx tsc --noEmit`, y un checklist manual.

---

### Task 1: Backend — rechazar nueva solicitud si ya hay una pendiente

**Files:**
- Modify: `app/routes/licenses.py` (agregar el chequeo dentro de `create_license_request`, el handler de `POST /request`)

**Interfaces:**
- Consumes: nada nuevo — usa la tabla `License` ya existente vía `db.execute(text(...))`, mismo patrón que el resto del endpoint.
- Produces: `POST /licenses/request` ahora responde `400` con `detail: "Ya tenés una solicitud de licencia pendiente de aprobación. Esperá la resolución antes de crear una nueva."` si el `employee_id` ya tiene una licencia en estado `'Pendiente'` o `'Pendiente Siguiente Aprobación'`.

- [ ] **Step 1: Agregar el chequeo al inicio de `create_license_request`, después de resolver `employee_id`**

Antes (líneas 348-368 de `app/routes/licenses.py`, el inicio del handler hasta la primera validación de negocio):
```python
@router.post("/request", dependencies=[Depends(require_any_auth)])
def create_license_request(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Crea una solicitud de licencia.
    """
    employee_id = data.get("employeeId") or data.get("solicitanteId")
    lic_type = data.get("type", "Licencias")
    start_date = data.get("startDate")
    end_date = data.get("endDate")
    message = data.get("originalMessage", "")
    status = data.get("status", "Pendiente")
    supervisor_user_id = data.get("supervisorId")
    duration = data.get("duration")

    if not employee_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Datos incompletos")

    # 1. Obtener datos del solicitante (Género, Antigüedad, Rol, Contrato)
    emp_query = text("""
        SELECT e.gender, e.name AS employee_name, cl.tipoContrato, cl.fechaIngreso, r.name as roleName
        FROM Employee e
        INNER JOIN CondicionLaboral cl ON e.id = cl.employeeId
        INNER JOIN [User] u ON u.employeeId = e.id
        INNER JOIN Role r ON u.roleId = r.id
        WHERE e.id = :empId
    """)
    emp_data = db.execute(emp_query, {"empId": employee_id}).mappings().first()
    if not emp_data:
        raise HTTPException(status_code=404, detail="Datos de empleado no encontrados")
```

Después:
```python
@router.post("/request", dependencies=[Depends(require_any_auth)])
def create_license_request(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Crea una solicitud de licencia.
    """
    employee_id = data.get("employeeId") or data.get("solicitanteId")
    lic_type = data.get("type", "Licencias")
    start_date = data.get("startDate")
    end_date = data.get("endDate")
    message = data.get("originalMessage", "")
    status = data.get("status", "Pendiente")
    supervisor_user_id = data.get("supervisorId")
    duration = data.get("duration")

    if not employee_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Datos incompletos")

    # Bloqueo: no se puede crear una nueva solicitud si ya hay una pendiente
    # (de cualquier tipo) sin resolver.
    pendiente = db.execute(text("""
        SELECT id FROM License
        WHERE employeeId = :empId
          AND status IN ('Pendiente', 'Pendiente Siguiente Aprobación')
    """), {"empId": employee_id}).fetchone()
    if pendiente:
        raise HTTPException(
            status_code=400,
            detail="Ya tenés una solicitud de licencia pendiente de aprobación. Esperá la resolución antes de crear una nueva."
        )

    # 1. Obtener datos del solicitante (Género, Antigüedad, Rol, Contrato)
    emp_query = text("""
        SELECT e.gender, e.name AS employee_name, cl.tipoContrato, cl.fechaIngreso, r.name as roleName
        FROM Employee e
        INNER JOIN CondicionLaboral cl ON e.id = cl.employeeId
        INNER JOIN [User] u ON u.employeeId = e.id
        INNER JOIN Role r ON u.roleId = r.id
        WHERE e.id = :empId
    """)
    emp_data = db.execute(emp_query, {"empId": employee_id}).mappings().first()
    if not emp_data:
        raise HTTPException(status_code=404, detail="Datos de empleado no encontrados")
```

- [ ] **Step 2: Verificar que el servidor levanta sin errores de sintaxis**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.routes.licenses"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/licenses.py
git commit -m "fix: rechazar nueva solicitud de licencia si ya hay una pendiente de aprobacion"
```

---

### Task 2: Frontend — deshabilitar "Nueva Solicitud" cuando hay una pendiente

**Files:**
- Modify: `RRHH/src/app/GestionLicencias/Licencias.tsx` (el componente `ConteinerLicencia`, botón "Solicitar")

**Interfaces:**
- Consumes: `misSolicitudes: LicenseHistory[]` (prop ya existente en `ConteinerLicencia`, ya poblada por el padre `LicenciasManage/Screen.tsx` desde `GET /licenses/requests?employee_id=...`). `LicenseHistory.status: LicenseStatus` (ya existe en `Interfaces.ts`).
- Produces: nada consumido por otros archivos — cambio contenido en este componente.

- [ ] **Step 1: Derivar si hay una solicitud pendiente**

Antes (línea 81 de `RRHH/src/app/GestionLicencias/Licencias.tsx`, el inicio del componente):
```tsx
export default function ConteinerLicencia({ userData, saldos, misSolicitudes, solicitudesPendientes, onNewRequest, onManageRequest, supervisores }: Props) {
```

Después (agregar la derivación justo después de la firma de la función — antes de cualquier otro `useState`/`useMemo` existente en el cuerpo del componente):
```tsx
export default function ConteinerLicencia({ userData, saldos, misSolicitudes, solicitudesPendientes, onNewRequest, onManageRequest, supervisores }: Props) {
  const tieneSolicitudPendiente = misSolicitudes.some(
    s => s.status === 'Pendiente' || s.status === 'Pendiente Siguiente Aprobación'
  );
```

- [ ] **Step 2: Deshabilitar el botón y mostrar el motivo**

Antes (líneas 164-178 de `RRHH/src/app/GestionLicencias/Licencias.tsx`):
```tsx
        {/* Nueva solicitud */}
        <div className="bg-gradient-to-br from-primary to-warm-contrast rounded-xl p-5 flex flex-col items-center justify-center text-center text-primary-foreground shadow-sm">
          <div className="w-10 h-10 rounded-full bg-primary-foreground/20 flex items-center justify-center mb-3">
            <Plus size={20} className="text-primary-foreground" />
          </div>
          <h3 className="font-semibold text-sm mb-1">Nueva Solicitud</h3>
          <p className="text-xs text-primary-foreground/80 mb-4">Iniciá tu solicitud de licencia</p>
          <button
            onClick={onNewRequest}
            className="flex items-center gap-1.5 px-4 py-2 bg-card text-primary text-xs font-semibold rounded-full hover:bg-muted transition shadow-sm"
          >
            <Send size={13} />
            Solicitar
          </button>
        </div>
```

Después:
```tsx
        {/* Nueva solicitud */}
        <div className="bg-gradient-to-br from-primary to-warm-contrast rounded-xl p-5 flex flex-col items-center justify-center text-center text-primary-foreground shadow-sm">
          <div className="w-10 h-10 rounded-full bg-primary-foreground/20 flex items-center justify-center mb-3">
            <Plus size={20} className="text-primary-foreground" />
          </div>
          <h3 className="font-semibold text-sm mb-1">Nueva Solicitud</h3>
          <p className="text-xs text-primary-foreground/80 mb-4">
            {tieneSolicitudPendiente
              ? 'Ya tenés una solicitud pendiente de aprobación'
              : 'Iniciá tu solicitud de licencia'}
          </p>
          <button
            onClick={onNewRequest}
            disabled={tieneSolicitudPendiente}
            title={tieneSolicitudPendiente ? 'Esperá la resolución de tu solicitud pendiente antes de crear otra.' : undefined}
            className="flex items-center gap-1.5 px-4 py-2 bg-card text-primary text-xs font-semibold rounded-full hover:bg-muted transition shadow-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-card"
          >
            <Send size={13} />
            Solicitar
          </button>
        </div>
```

- [ ] **Step 3: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "GestionLicencias/Licencias"`
Expected: ningún resultado (sin errores nuevos en este archivo).

- [ ] **Step 4: Commit**

```bash
git add src/app/GestionLicencias/Licencias.tsx
git commit -m "feat: deshabilitar boton de nueva solicitud si ya hay una pendiente"
```

---

### Task 3: Frontend — calendario de un solo mes

**Files:**
- Modify: `RRHH/src/app/GestionLicencias/Calendario.tsx`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: nada consumido por otros archivos.

- [ ] **Step 1: Cambiar `numberOfMonths` a `1` siempre**

Antes (línea 146 de `RRHH/src/app/GestionLicencias/Calendario.tsx`, dentro del componente `Calendar` de PrimeReact):
```tsx
          numberOfMonths={isMobile ? 1 : 2}
```

Después:
```tsx
          numberOfMonths={1}
```

- [ ] **Step 2: Confirmar si `isMobile`/`useIsMobile` quedan sin otro uso en el archivo**

Run: `grep -n "isMobile" RRHH/src/app/GestionLicencias/Calendario.tsx`
Si `isMobile` (la variable, no el hook `useIsMobile`) ya no se usa en ningún otro lugar del archivo tras el Step 1, eliminar también la línea `const isMobile = useIsMobile();` y, si `useIsMobile` (el hook completo) queda sin ningún llamador, eliminar también la función `useIsMobile` y el `useState`/`useEffect` que la componen. Si `isMobile` todavía se usa en otro lugar (por ejemplo para otro ajuste responsive), dejar todo como está y solo aplicar el Step 1.

- [ ] **Step 3: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "GestionLicencias/Calendario"`
Expected: ningún resultado (sin errores nuevos en este archivo, y sin warnings de variable no usada que rompan el build).

- [ ] **Step 4: Commit**

```bash
git add src/app/GestionLicencias/Calendario.tsx
git commit -m "feat: mostrar un solo mes en el calendario de seleccion de fechas"
```

---

### Task 4: Verificación manual end-to-end

**Files:** ninguno (solo verificación, no produce commits de código).

**Interfaces:**
- Consumes: el flujo completo de las Tasks 1-3.
- Produces: confirmación de que el comportamiento documentado en la spec se cumple.

- [ ] **Step 1: Levantar ambos servidores**

Backend: `uvicorn app.main:app --reload` (desde `Backend_RRHH`)
Frontend: `npm run dev` (desde `RRHH`)

- [ ] **Step 2: Confirmar bloqueo de solicitud duplicada**

Como empleado, crear una solicitud de licencia (queda en estado Pendiente). Confirmar que el botón "Solicitar" en la tarjeta "Nueva Solicitud" aparece deshabilitado, con el texto "Ya tenés una solicitud pendiente de aprobación".

- [ ] **Step 3: Confirmar bloqueo a nivel backend**

Con la solicitud del Step 2 todavía pendiente, intentar `POST /licenses/request` directamente (vía `curl` o similar) para ese mismo empleado, con cualquier tipo de licencia — debe devolver 400 con el mensaje del bloqueo.

- [ ] **Step 4: Confirmar que se libera al resolver**

Como supervisor, aprobar o rechazar la solicitud pendiente del Step 2. Volver a la pantalla del empleado — confirmar que el botón "Solicitar" vuelve a estar habilitado.

- [ ] **Step 5: Confirmar el calendario compacto**

Abrir el formulario de nueva solicitud (con el botón ya habilitado). Confirmar que el calendario muestra un solo mes, sin necesidad de scroll horizontal, tanto en una ventana de escritorio como en una angosta (mobile).
