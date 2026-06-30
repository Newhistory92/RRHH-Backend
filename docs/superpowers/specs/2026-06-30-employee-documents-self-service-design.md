# Documentos en el perfil del empleado (solo lectura)

## Contexto

El módulo RRHH ya permite a RRHH/Admin adjuntar documentos (PDF/imágenes) al legajo de un empleado, vía la tab "Documentos" en `Perfildetail.tsx` (ver `docs/superpowers/specs/2026-06-30-employee-documents-design.md`). El empleado dueño de esos documentos no tiene forma de verlos — solo RRHH puede acceder a `GET /rrhh/employee/{id}/documents` (gateado por `require_roles(ROLE_ADMIN, ROLE_RRHH)`).

Se agrega una vista de solo lectura en el menú del navbar del empleado para que pueda ver (no subir ni borrar) los documentos que RRHH le adjuntó.

## Backend

Dos endpoints nuevos en `app/routes/employee.py` (mismo archivo que ya tiene el patrón self-or-admin del fix de CV — `current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN` → 403), reutilizando las funciones de `app/database/employee_documents.py` ya existentes (`get_documents`, `get_document`) — sin tocar la tabla ni agregar acceso a datos nuevo:

- `GET /employee/{employee_id}/documents` — lista sin `fileData`. Mismo chequeo self-or-admin.
- `GET /employee/{employee_id}/documents/{document_id}/download` — documento completo (incl. `fileData`) para visualizar. Mismo chequeo self-or-admin. 404 si no existe.

Sin endpoints de carga ni borrado — el empleado es estrictamente de solo lectura.

## Frontend

- **`Page` type** (`src/app/Interfas/Interfaces.ts`): se agrega el valor `"documentos"`.
- **`AppHeader.tsx`**: nuevo ítem "Documentos" en el dropdown del perfil, entre "Licencias" y "Encuesta", con `onClick={() => setPage("documentos")}` (mismo patrón que los 3 ítems existentes, sin chequeo de rol — visible para cualquier usuario autenticado, igual que los demás).
- **`page.tsx`**: nuevo `case 'documentos': return <MisDocumentos employeeData={employeeData} />;` en el switch de `renderContent()`.
- **Nueva pantalla `src/app/screens/MisDocumentos/Screen.tsx`**: tabla de solo lectura (tipo, descripción, nombre de archivo, fecha, botón "Ver"). Reutiliza exactamente la misma lógica de blob-URL para visualizar/imprimir que ya se corrigió en `DocumentsTab` (`DetailTables.tsx`) — decodifica el base64 a `Blob`, abre con `URL.createObjectURL`, sin formulario de carga ni botón de eliminar.

## Fuera de alcance

- Que el empleado pueda subir o eliminar sus propios documentos.
- Notificaciones cuando RRHH carga un documento nuevo.
- Filtros o búsqueda en la lista (alcance pequeño, no se justifica todavía).

## Testing

- No hay test suite automatizado en ninguno de los dos repos — verificación manual:
  1. Como RRHH, cargar un documento para un empleado (ya implementado).
  2. Loguearse como ese empleado, abrir el menú del navbar → "Documentos" → confirmar que aparece el documento cargado.
  3. Tocar "Ver" → confirmar que se abre/imprime correctamente.
  4. Confirmar que el empleado NO ve botones de carga ni de eliminar.
  5. Como otro empleado (no el dueño), intentar `GET /employee/{id}/documents` con un `id` ajeno (vía curl) — debe devolver 403.
  6. Como Admin, confirmar que puede ver los documentos de cualquier empleado.
