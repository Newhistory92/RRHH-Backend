# Reubicación — Ejecución en el Organigrama Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cuarto y último subsistema de Reubicación Inteligente: un botón "Ejecutar" sobre las solicitudes `Aprobada` que mueve al empleado a su nueva oficina/departamento en el organigrama, reasigna su jefe directo, notifica, y pasa la solicitud a `Ejecutada`.

**Architecture:** Un endpoint nuevo `PATCH /reubicacion/{id}/ejecutar` en el backend (mismo archivo `reubicacion.py` de los subsistemas 1-3), que en una sola transacción mueve al `Employee` y actualiza `SolicitudReubicacion`. En el frontend, el mismo tablero (`ReubicacionTablero/Screen.tsx`) gana un botón y un diálogo de confirmación con selector de oficina destino.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- Solo se puede ejecutar una solicitud en estado `Aprobada`; cualquier otro estado → 400.
- El body requiere `officeId`; si falta → 400 (cubre el caso de aprobación a ciegas sin destino).
- `managerId` del empleado se reasigna al `jefeId` de la oficina destino; si esa oficina no tiene jefe, o el jefe sería el propio empleado, `managerId` queda `NULL`.
- Todo (mover al `Employee`, actualizar la `SolicitudReubicacion`, notificar) va en una sola transacción: todo o nada.
- Notificación al empleado vía `INSERT INTO Message` (mismo patrón que subsistemas 2 y 3: `days=0`, `status='active'`, `startDate=endDate=now`).
- **Sin cambios de esquema** — `officeIdDestino`/`departmentIdDestino` ya existen desde el subsistema 3 (`ensure_table()` no se toca).
- `require_rrhh_auth` para el endpoint nuevo (ya definido en el archivo: `require_roles(ROLE_ADMIN, ROLE_RRHH)`).
- No se modifica ningún otro endpoint de `reubicacion.py` (`/request`, `/mis-solicitudes/{id}`, `/solicitudes`, `/{id}/estado`, `/analizar/iniciar`, `/{id}/recomendacion`).
- Sin test suite automatizada en ninguno de los dos repos — verificación por `py_compile`/`tsc --noEmit` filtrado, y verificación manual final.

---

### Task 1: Backend — endpoint `PATCH /reubicacion/{id}/ejecutar`

**Files:**
- Modify: `app/routes/reubicacion.py`

**Interfaces:**
- Produces: `PATCH /reubicacion/{solicitud_id}/ejecutar` (`require_rrhh_auth`), body `{"officeId": int}` → `{"message": "Reubicación ejecutada", "estado": "Ejecutada"}`.

- [ ] **Step 1: Agregar el endpoint al final de `app/routes/reubicacion.py`**

Ubicar el final del archivo (después de la función `guardar_recomendacion`, que termina en `return {"message": "Recomendación guardada", "estado": "Recomendada"}`), y agregar debajo:

```python


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/ejecutar — mueve al empleado en el
# organigrama (Employee.officeId/departmentId/managerId) y pasa a 'Ejecutada'.
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/ejecutar", dependencies=[Depends(require_rrhh_auth)])
def ejecutar_solicitud(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Ejecuta una solicitud Aprobada: mueve al empleado en el organigrama y notifica."""
    office_id = data.get("officeId")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id, employeeId, estado FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if solicitud["estado"] != "Aprobada":
        raise HTTPException(status_code=400, detail="Solo se pueden ejecutar solicitudes en estado 'Aprobada'")

    if not office_id:
        raise HTTPException(status_code=400, detail="Debe indicar la oficina destino para ejecutar")

    office = db.execute(text("""
        SELECT id, departmentId, jefeId, nombre FROM Office WHERE id = :id
    """), {"id": office_id}).mappings().first()
    if not office:
        raise HTTPException(status_code=404, detail="Oficina no encontrada")

    employee_id = solicitud["employeeId"]
    jefe_id = office["jefeId"]
    manager_id = jefe_id if jefe_id and jefe_id != employee_id else None

    db.execute(text("""
        UPDATE Employee
        SET officeId = :officeId, departmentId = :departmentId, managerId = :managerId
        WHERE id = :employeeId
    """), {
        "officeId": office["id"], "departmentId": office["departmentId"],
        "managerId": manager_id, "employeeId": employee_id,
    })

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'Ejecutada', officeIdDestino = :officeId, departmentIdDestino = :departmentId, updatedAt = :now
        WHERE id = :id
    """), {
        "officeId": office["id"], "departmentId": office["departmentId"],
        "now": now, "id": solicitud_id,
    })

    msg_text = f"Tu reubicación fue ejecutada. Nueva oficina: {office['nombre']}."
    db.execute(text("""
        INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
        VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
    """), {"empId": employee_id, "msg": msg_text, "now": now})

    db.commit()

    return {"message": "Reubicación ejecutada", "estado": "Ejecutada"}
```

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/routes/reubicacion.py`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
git add app/routes/reubicacion.py
git commit -m "feat: agregar endpoint de ejecucion de reubicacion en el organigrama"
```

---

### Task 2: Frontend — botón "Ejecutar" y diálogo de confirmación

**Files:**
- Modify: `src/app/screens/ReubicacionTablero/Screen.tsx`

**Interfaces:**
- Consumes: `PATCH /reubicacion/{id}/ejecutar` (Task 1), body `{officeId: number}`.
- Produces: ningún consumidor externo — es la pantalla final.

- [ ] **Step 1: Agregar el estado nuevo para el diálogo de ejecución**

Reemplazar:
```tsx
  const [seleccionada, setSeleccionada] = useState<{ solicitud: SolicitudRRHH; accion: 'Aprobada' | 'Rechazada' } | null>(null);
  const [observacion, setObservacion] = useState('');
  const [destinoSeleccionado, setDestinoSeleccionado] = useState<number | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [analizando, setAnalizando] = useState(false);
  const [verRecomendacion, setVerRecomendacion] = useState<SolicitudRRHH | null>(null);
  const toast = useRef<Toast>(null);
```
por:
```tsx
  const [seleccionada, setSeleccionada] = useState<{ solicitud: SolicitudRRHH; accion: 'Aprobada' | 'Rechazada' } | null>(null);
  const [observacion, setObservacion] = useState('');
  const [destinoSeleccionado, setDestinoSeleccionado] = useState<number | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [analizando, setAnalizando] = useState(false);
  const [verRecomendacion, setVerRecomendacion] = useState<SolicitudRRHH | null>(null);
  const [paraEjecutar, setParaEjecutar] = useState<SolicitudRRHH | null>(null);
  const [officeEjecucion, setOfficeEjecucion] = useState<number | null>(null);
  const [ejecutando, setEjecutando] = useState(false);
  const toast = useRef<Toast>(null);
```

- [ ] **Step 2: Agregar `abrirEjecucion` y `confirmarEjecucion`**

Ubicar el bloque (justo después del cierre de `confirmarAccion`, antes de `const puedeAccionar = ...`):
```tsx
  const puedeAccionar = (estado: string) => estado === 'Pendiente' || estado === 'Recomendada';
```
y reemplazarlo por:
```tsx
  const abrirEjecucion = (solicitud: SolicitudRRHH) => {
    setParaEjecutar(solicitud);
    setOfficeEjecucion(solicitud.officeIdDestino ?? null);
  };

  const confirmarEjecucion = async () => {
    if (!paraEjecutar || !officeEjecucion) return;
    setEjecutando(true);
    try {
      await apiClient.patch(`/reubicacion/${paraEjecutar.id}/ejecutar`, {
        officeId: officeEjecucion,
      });
      toast.current?.show({ severity: 'success', summary: 'Ejecutada', detail: 'Reubicación ejecutada correctamente', life: 3000 });
      setParaEjecutar(null);
      await cargarSolicitudes();
    } catch (err) {
      console.error('Error al ejecutar la solicitud:', err);
      toast.current?.show({ severity: 'error', summary: 'Error', detail: 'No se pudo ejecutar la reubicación', life: 4000 });
    } finally {
      setEjecutando(false);
    }
  };

  const puedeAccionar = (estado: string) => estado === 'Pendiente' || estado === 'Recomendada';
```

- [ ] **Step 3: Agregar el componente `BotonEjecutar`**

Reemplazar:
```tsx
  const VerRecomendacionBoton = ({ s }: { s: SolicitudRRHH }) => (
    s.estado === 'Recomendada' && s.scoreCompatibilidad !== null ? (
      <Button
        label="Ver recomendación"
        icon="pi pi-eye"
        text
        size="small"
        className="w-full mt-1"
        onClick={() => setVerRecomendacion(s)}
      />
    ) : null
  );
```
por:
```tsx
  const VerRecomendacionBoton = ({ s }: { s: SolicitudRRHH }) => (
    s.estado === 'Recomendada' && s.scoreCompatibilidad !== null ? (
      <Button
        label="Ver recomendación"
        icon="pi pi-eye"
        text
        size="small"
        className="w-full mt-1"
        onClick={() => setVerRecomendacion(s)}
      />
    ) : null
  );

  const BotonEjecutar = ({ s }: { s: SolicitudRRHH }) => (
    s.estado === 'Aprobada' ? (
      <Button
        label="Ejecutar"
        icon="pi pi-directions"
        severity="success"
        size="small"
        className="w-full mt-2"
        onClick={() => abrirEjecucion(s)}
      />
    ) : null
  );
```

- [ ] **Step 4: Mostrar el botón en la vista Kanban**

Reemplazar:
```tsx
                    <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                    <VerRecomendacionBoton s={s} />
                    <AccionesSolicitud s={s} />
                  </div>
                ))}
              </div>
            ))}
          </div>
```
por:
```tsx
                    <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                    <VerRecomendacionBoton s={s} />
                    <AccionesSolicitud s={s} />
                    <BotonEjecutar s={s} />
                  </div>
                ))}
              </div>
            ))}
          </div>
```

- [ ] **Step 5: Mostrar el botón en la vista Tabla**

Reemplazar:
```tsx
                    <td className="py-2 px-3 text-muted-foreground">{formatDate(s.createdAt)}</td>
                    <td className="py-2 px-3">
                      <VerRecomendacionBoton s={s} />
                      <AccionesSolicitud s={s} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
```
por:
```tsx
                    <td className="py-2 px-3 text-muted-foreground">{formatDate(s.createdAt)}</td>
                    <td className="py-2 px-3">
                      <VerRecomendacionBoton s={s} />
                      <AccionesSolicitud s={s} />
                      <BotonEjecutar s={s} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
```

- [ ] **Step 6: Agregar el diálogo de ejecución**

Reemplazar:
```tsx
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
```
por:
```tsx
            </div>
          </div>
        )}
      </Dialog>

      <Dialog
        header={paraEjecutar ? `Ejecutar reubicación de ${paraEjecutar.employeeName}` : ''}
        visible={!!paraEjecutar}
        onHide={() => setParaEjecutar(null)}
        style={{ width: '28rem' }}
        modal
      >
        <div className="space-y-3">
          <label className="block text-sm font-semibold text-foreground mb-1">Oficina destino</label>
          <Dropdown
            value={officeEjecucion}
            options={officeOptions}
            onChange={(e) => setOfficeEjecucion(e.value)}
            placeholder="Seleccionar oficina"
            className="w-full"
          />
          <p className="text-xs text-muted-foreground">
            Se moverá al empleado a esta oficina/departamento y se actualizará el organigrama.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button label="Cancelar" className="p-button-text" onClick={() => setParaEjecutar(null)} />
            <Button
              label="Confirmar"
              severity="success"
              loading={ejecutando}
              disabled={!officeEjecucion}
              onClick={confirmarEjecucion}
            />
          </div>
        </div>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 7: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "screens/ReubicacionTablero/Screen"`
Expected: sin salida (sin errores nuevos en este archivo).

- [ ] **Step 8: Commit**

```bash
git add src/app/screens/ReubicacionTablero/Screen.tsx
git commit -m "feat: agregar boton y dialogo de ejecucion al tablero de reubicacion"
```

---

### Task 3: Verificación manual

No hay test suite automatizada en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `PATCH /reubicacion/{id}/ejecutar` sobre una solicitud `Aprobada` con un `officeId` válido: mueve al `Employee` (officeId/departmentId/managerId correctos) y pasa la solicitud a `Ejecutada`.
- [ ] **Step 3:** Confirmar que `managerId` queda con el `jefeId` de la oficina destino; si la oficina no tiene jefe, o el jefe sería el propio empleado, `managerId` queda `NULL`.
- [ ] **Step 4:** `PATCH /ejecutar` sobre una solicitud en cualquier otro estado (`Pendiente`, `Recomendada`, `Rechazada`, `Ejecutada`) devuelve 400; sobre un `id` inexistente devuelve 404; sin `officeId` devuelve 400; con un `officeId` inexistente devuelve 404.
- [ ] **Step 5:** En el módulo Organigrama, verificar que el empleado aparece efectivamente en su nueva oficina/departamento tras ejecutar.
- [ ] **Step 6:** En el frontend, el botón "Ejecutar" solo aparece en solicitudes `Aprobada`. Al abrir el diálogo, si la solicitud tenía `officeIdDestino` guardado (aprobada con destino), el dropdown viene pre-cargado; si se aprobó a ciegas, viene vacío y "Confirmar" está deshabilitado hasta elegir una oficina.
- [ ] **Step 7:** Tras confirmar la ejecución, la tarjeta/fila se mueve a la columna/estado `Ejecutada` al recargar el tablero.
- [ ] **Step 8:** El empleado recibe la notificación de ejecución en la campanita del header al loguearse.
