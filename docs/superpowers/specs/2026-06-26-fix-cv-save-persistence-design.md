# Fix: Persistencia del guardado de CV

## Contexto

El frontend (`RRHH/src/app/screens/Cv/Screen.tsx`) envía el objeto completo `Employee` vía `PUT /employee/{id}` al guardar el CV. El backend responde 200 OK pero descarta silenciosamente la mayoría de las secciones — el usuario cree que guardó, pero al recargar la página los cambios desaparecieron. Originalmente reportado como "las habilidades blandas no se guardan", la causa real es más amplia.

## Diagnóstico

`app/routes/employee.py:602`, función `update_employee`:

1. **Permisos**: `dependencies=[Depends(require_roles(ROLE_ADMIN))]` — solo un usuario con rol admin puede llamar este endpoint. Un empleado común editando su propio CV recibe 403 (o, si el frontend no maneja ese caso, el guardado falla sin feedback claro).
2. **Persistencia incompleta**: el handler solo escribe:
   - `employee_fields` = `["name", "email", "birthDate", "address", "phone", "photo", "horas", "departmentId", "officeId"]` (UPDATE directo sobre `Employee`).
   - `AcademicFormation` (DELETE + INSERT por registro, solo si `data.get("AcademicFormation")` es truthy).

   Todo lo demás que el frontend envía (`workExperience`, `languages`, `certifications`, `technicalSkills`, `softSkillsArray`) se ignora — nunca se lee de `data`, nunca se escribe en su tabla correspondiente.

## Decisiones

- **Permisos**: se cambia la dependencia a `require_any_auth` (cualquier usuario autenticado) y se agrega un chequeo inline: si `current_user["employeeId"] != employee_id` y `current_user["roleId"] != ROLE_ADMIN`, se devuelve 403. Mismo patrón que ya usa `get_current_user` en otras rutas (retorna `{usuario, roleId, employeeId}` desde el JWT).
- **Persistencia**: se extiende el patrón ya usado para `AcademicFormation` (DELETE por `employeeId` + INSERT por elemento recibido, solo si la clave está presente en el body) a las 4 secciones restantes. Esto preserva el comportamiento actual de "no tocar lo que no se envía" — si una llamada de guardado no incluye `languages`, no se borran los idiomas existentes.
- **Mapeo de campos**: cada sección usa exactamente las columnas que ya lee el `GET /{employee_id}` existente (mismo archivo, líneas ~96-186), para que lo que se guarda sea exactamente lo que se vuelve a leer.
- **Transacción única**: todas las secciones se escriben dentro del mismo `try/except` con un solo `db.commit()` al final (como ya hace el código actual) — si una sección falla, se hace rollback de todo el guardado, no solo de esa sección.

## Mapeo de secciones a persistir

| Campo en `data` (JSON del body) | Tabla destino | Columnas en el INSERT |
|---|---|---|
| `workExperience` (array) | `WorkExperience` | `employeeId, position, company, industry, location, startDate, endDate, isCurrent, activo=1, contractType` |
| `languages` (array) | `Language` | `employeeId, language, level, certification, activo=1, attachment` |
| `certifications` (array) | `Certification` | `employeeId, name, institution, issueDate (=record["date"]), validUntil, activo=1, attachment` |
| `technicalSkills` (array) | `EmployeeTechnicalSkill` | `employeeId, technicalSkillId, level, certified` |
| `softSkillsArray` (array de IDs numéricos) | `EmployeeSoftSkill` | `employeeId, softSkillId (=cada elemento del array), level=NULL, skillStatusId=NULL` |

Notas sobre los nombres de campo del frontend (`RRHH/src/app/Interfas/Interfaces.ts`):
- `certifications[].date` (frontend) → columna `issueDate` (backend) — el GET ya hace este mismo mapeo a la inversa.
- `softSkillsArray: number[]` es la lista de IDs de `SoftSkill` seleccionados (no `softSkills: SoftSkill[]`, que es un campo legado sin uso real en el flujo de guardado — no se persiste, queda fuera de alcance tocarlo).
- `technicalSkills[].certified: boolean` y `.level: string | null` se escriben tal cual.

## Fuera de alcance

- Validación de integridad referencial de `technicalSkillId`/`softSkillId` más allá de la FK de la base de datos.
- El flujo de validación de habilidades técnicas vía test con IA (`TestModal`/`SkillTest`, endpoints `/tests/skills/*`) — ya tiene su propio mecanismo de persistencia, no se toca.
- El hardcode de `SPECIAL_TITLE_MAPPINGS` en `HabilidadesTecnicas.tsx` (frontend) — sesión futura separada.
- Mejoras de UX del flujo de edición de CV — sesión futura separada.
- El campo legado `softSkills: SoftSkill[]` (sin persistencia real, no confundir con `softSkillsArray`).

## Testing

- Verificación manual: editar CV de un empleado de prueba (rol no-admin, editando su propio perfil) agregando una experiencia laboral, un idioma, una certificación, validando una habilidad técnica y seleccionando una habilidad blanda — guardar, recargar la página, confirmar que los 5 cambios persisten.
- Verificación de permisos: confirmar que un empleado no puede editar el CV de otro empleado (403), y que un admin sí puede editar el de cualquiera.
- No hay test suite automatizado en este backend; la verificación es manual end-to-end vía el frontend o `curl` directo al endpoint.
