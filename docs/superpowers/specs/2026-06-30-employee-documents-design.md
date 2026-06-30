# Adjuntar Documentación (módulo RRHH)

## Contexto

Al ingresar al detalle de un empleado en el módulo RRHH (`Perfildetail.tsx` → tabs `ProfileTab`/`LicenseHistoryTab`/`PermissionHistoryTab` en `DetailTables.tsx`), no existe forma de adjuntar documentación del legajo (DNI, resoluciones, certificados, etc.). Se agrega una pestaña nueva "Documentos" donde RRHH puede cargar PDFs e imágenes, con una descripción y un tipo de documento.

## Decisión: almacenamiento

Este backend no tiene infraestructura de archivos (sin `UploadFile`/multipart, sin carpeta de uploads, sin `StaticFiles` montado en `app/main.py`). El único patrón de carga de archivos que ya funciona en el codebase es el de la foto de perfil (`ProfilePictureUploader` en `RRHH/src/app/util/UiRRHH.tsx`): el archivo se convierte a base64 en el navegador (`FileReader.readAsDataURL`) y se guarda como texto en una columna de la base.

Se replica ese mismo patrón para los documentos — sin agregar infraestructura nueva (sin carpeta de uploads, sin `StaticFiles`, sin cambios a `app/main.py`).

## Modelo de datos

Tabla nueva `EmployeeDocument`, creada de forma idempotente (`IF NOT EXISTS`, mismo patrón que `app/database/academic_title_mapping.py` y `app/database/token_blacklist.py`), `ensure_table()` invocada al inicio de cada endpoint nuevo (no se toca `app/main.py`):

| Columna | Tipo | Notas |
|---|---|---|
| id | INT IDENTITY PK | |
| employeeId | INT NOT NULL | |
| tipo | NVARCHAR(100) NOT NULL | uno de los 20 tipos hardcodeados (ver abajo) |
| descripcion | NVARCHAR(500) NULL | texto libre |
| fileName | NVARCHAR(255) NOT NULL | nombre original del archivo |
| mimeType | NVARCHAR(100) NOT NULL | `application/pdf`, `image/jpeg`, `image/png` |
| fileData | NVARCHAR(MAX) NOT NULL | base64 del archivo |
| activo | BIT NOT NULL DEFAULT 1 | soft delete |
| createdAt | DATETIME2 NOT NULL | |

## Backend

Endpoints nuevos en `app/routes/rrhh.py` (mismo router, mismo permiso `require_roles(ROLE_ADMIN, ROLE_RRHH)` que ya usan todos los demás endpoints de este archivo):

- `GET /rrhh/employee/{employee_id}/documents` — lista documentos activos **sin** `fileData` (liviano): `{id, tipo, descripcion, fileName, mimeType, createdAt}[]`.
- `POST /rrhh/employee/{employee_id}/documents` — body `{tipo, descripcion, fileName, mimeType, fileData}`. Valida `tipo`/`fileName`/`mimeType`/`fileData` no vacíos (400 si falta alguno).
- `GET /rrhh/employee/{employee_id}/documents/{document_id}/download` — devuelve el registro completo incluyendo `fileData`, para que el frontend arme una data URL y lo abra/descargue.
- `DELETE /rrhh/employee/{employee_id}/documents/{document_id}` — soft delete (`activo = 0`). 404 si no existe.

Módulo de datos `app/database/employee_documents.py` (mismo patrón que `academic_title_mapping.py`): `ensure_table(db)`, `get_documents(db, employee_id)`, `get_document(db, employee_id, document_id)`, `save_document(db, employee_id, tipo, descripcion, file_name, mime_type, file_data)`, `delete_document(db, employee_id, document_id) -> bool`.

## Frontend

**`DocumentsTab`** (nuevo componente, mismo archivo y patrón que `ProfileTab`/`LicenseHistoryTab` en `RRHH/src/app/Componentes/TablaOperador/DetailTables.tsx`), agregado como tab nueva en `Perfildetail.tsx`:

- **Formulario de carga**: `Dropdown` "Tipo de documento" (20 opciones hardcodeadas en el componente, ver lista abajo), `InputText` "Descripción" (opcional), input de archivo (`accept=".pdf,.jpg,.jpeg,.png"`), botón "Subir documento". Al seleccionar el archivo, se convierte a base64 vía `FileReader.readAsDataURL` (mismo patrón que `ProfilePictureUploader`) y se hace `POST` al backend; al terminar, se refresca la lista.
- **Lista de documentos**: tabla con tipo, descripción, nombre de archivo, fecha, botón "Ver/Descargar" (hace `GET .../download`, arma `data:${mimeType};base64,${fileData}` y lo abre en una pestaña nueva con `window.open`) y botón "Eliminar" (con confirmación, `DELETE` + refresco de lista).

**20 tipos de documento** (hardcodeados como `const DOCUMENT_TYPES: string[]` en el componente):
DNI, CUIL, Resolución, Título Académico, Certificado Médico, Certificado de Antecedentes Penales, Constancia de CBU, Constancia de AFIP, Curriculum Vitae, Contrato de Trabajo, Recibo de Sueldo, Apto Psicofísico, Carnet de Obra Social, Licencia de Conducir, Foto Carnet, Declaración Jurada, Certificado de Estudios, Comprobante de Domicilio, Acta de Matrimonio, Otro.

## Fuera de alcance

- Que el empleado vea sus propios documentos desde el CV — no se pidió, solo RRHH carga/ve.
- Validación de tamaño máximo de archivo.
- OCR o extracción automática de datos del documento.
- Migrar el resto de los `attachment` existentes (Certification, AcademicFormation, etc., que hoy no persisten realmente — son `File` objects que nunca se serializan) a este mismo patrón — fuera de alcance, no se toca.

## Testing

- No hay test suite automatizado en ninguno de los dos repos — verificación manual:
  1. Como RRHH, entrar al detalle de un empleado, ir a la tab "Documentos".
  2. Subir un PDF con tipo "DNI" y una descripción — confirmar que aparece en la lista.
  3. Subir una imagen JPG con otro tipo — confirmar que también aparece.
  4. Tocar "Ver/Descargar" en cada uno — confirmar que se abre correctamente en una pestaña nueva.
  5. Eliminar un documento — confirmar que desaparece de la lista y, recargando la página, sigue sin aparecer.
  6. Confirmar que un usuario sin rol RRHH/Admin no puede acceder a estos endpoints (403).
