# Bloqueo de solicitudes concurrentes + calendario más compacto

## Contexto

Reportado tras el fix del envío de licencias (sesión anterior): mientras una solicitud de licencia está pendiente de aprobación, el empleado puede seguir creando solicitudes nuevas sin límite, sin que el saldo se descuente hasta la aprobación. Además, el selector de fechas (`Calendario.tsx`) muestra 2 meses lado a lado en modo `inline`, lo que en contenedores angostos obliga a hacer scroll horizontal y da la sensación de que "se mueve solo" o "se ve la mitad".

Son 2 piezas independientes, sin código compartido.

## A. Bloquear nuevas solicitudes mientras hay una pendiente

**Decisión de alcance** (confirmada con el usuario): el bloqueo es global — una sola solicitud pendiente, de **cualquier tipo**, impide crear cualquier otra, hasta que se resuelva (aprobada o rechazada).

**Backend**: en `POST /licenses/request` (`app/routes/licenses.py`), antes del INSERT, se agrega una consulta:

```sql
SELECT id FROM License WHERE employeeId = :empId AND status IN ('Pendiente', 'Pendiente Siguiente Aprobación')
```

Si existe una fila, se responde `400 Bad Request` con `detail: "Ya tenés una solicitud de licencia pendiente de aprobación. Esperá la resolución antes de crear una nueva."`. Esta validación se agrega junto a las validaciones de negocio ya existentes en el mismo endpoint (género, antigüedad, rol, ventana de vacaciones).

**Frontend**: `LicenciasManage/Screen.tsx` ya carga `misSolicitudes` (historial propio) al montar. Se deriva `tieneSolicitudPendiente = misSolicitudes.some(s => s.status === 'Pendiente' || s.status === 'Pendiente Siguiente Aprobación')` y se pasa como prop a `ConteinerLicencia` (el botón "Nueva Solicitud" ya vive ahí). Si es `true`, el botón se deshabilita y muestra un tooltip/texto corto explicando por qué — evitando que el usuario llegue al formulario para encontrarse recién ahí con el error 400. El backend igual valida (defensa en profundidad, por si el estado local quedó desactualizado).

## B. Calendario compacto (1 mes visible)

En `RRHH/src/app/GestionLicencias/Calendario.tsx`, el componente `Calendar` de PrimeReact usa `numberOfMonths={isMobile ? 1 : 2}`. Se cambia a `numberOfMonths={1}` siempre (mobile y desktop), eliminando la necesidad de `overflow-x-auto`/scroll horizontal para ver el mes completo. El resto de la configuración (`selectionMode="range"`, `disabledDays`, `disabledDates`, `dateTemplate` para feriados) no cambia — solo se reduce a un mes por vista, navegable con las flechas propias del calendario.

## Fuera de alcance

- Cancelar una solicitud pendiente desde la UI del empleado (no se pidió).
- Cambiar el flujo de aprobación/derivación de supervisores.
- Rediseñar el date-picker como popup — se descartó esa opción a favor de mantener el modo inline, solo más angosto.

## Testing

- No hay test suite automatizado en ninguno de los dos repos — verificación manual:
  1. Crear una solicitud de licencia (queda en estado Pendiente).
  2. Confirmar que el botón "Nueva Solicitud" aparece deshabilitado con un mensaje explicando por qué.
  3. Intentar `POST /licenses/request` directamente (vía curl) para ese mismo empleado — debe devolver 400.
  4. Aprobar o rechazar esa solicitud (como supervisor) — confirmar que el botón vuelve a habilitarse.
  5. Abrir el formulario de nueva solicitud y confirmar que el calendario muestra un solo mes, sin scroll horizontal, en desktop y mobile.
