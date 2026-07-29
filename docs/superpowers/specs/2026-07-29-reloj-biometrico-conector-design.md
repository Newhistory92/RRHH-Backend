# Spec: Conector ISAPI de relojes biométricos + vínculo de identidad

**Fecha:** 2026-07-29
**Alcance:** Subsistemas 1 y 2 de 6 (ver "Descomposición")

## Contexto

La institución tiene dos relojes biométricos Hikvision **DS-K1T320MFWX** que hoy
solo se consultan a través de iVMS-4200 y exportaciones manuales a CSV. El
objetivo es leer las marcaciones directamente por ISAPI desde el backend, sin
depender de iVMS-4200 ni de archivos intermedios.

### Hallazgos verificados en vivo (2026-07-29)

Todo lo que sigue fue comprobado contra los equipos reales, no asumido:

| Hallazgo | Detalle |
|---|---|
| Puerto ISAPI | **80**, no 8000. El 8000 es del SDK propietario |
| Autenticación | HTTP **Digest** |
| Equipos | `10.25.2.24` (247 usuarios) y `10.25.2.25` "Reloj 01" (236 usuarios) |
| Firmware | V3.5.2 |
| Marcación válida | `major=5`, `minor=38` (`fpOrface`) |
| Ruido a descartar | `minor=21` / `minor=22` — aperturas de puerta, sin persona asociada |
| Campos útiles | `employeeNoString`, `name`, `time`, `serialNo`, `currentVerifyMode` |
| Timezone | El equipo devuelve hora local con offset `-03:00` |
| Entrada/salida | **El reloj NO lo distingue.** No existe `attendanceStatus` en los eventos |
| Correlativo | `serialNo` incremental **por equipo** (ej. 168409) |
| Filtro por persona | `employeeNoString` funciona dentro de `AcsEventCond` |
| Historial disponible | `.24` desde 2026-02-03 (24.501) · `.25` desde 2025-08-01 (18.251) |
| Volumen último mes | **5.627 marcaciones** (4.055 + 1.572) |

Caso de referencia — Zalazar Beatriz (`employeeNo` 50), 2026-07-28:

```
Reloj .24 → 06:08:29  y  13:02:22   (exactamente 2 marcaciones)
Reloj .25 → 0 marcaciones
```

De ahí se desprende que **la primera marcación del día es la entrada y la última
es la salida**, y que **cada persona usa un equipo u otro** (puertas distintas),
por lo que el conector debe leer ambos y fusionarlos en una sola línea de tiempo
por empleado.

### Estado actual del sistema

- `Employee.cronogramaId` → `Horario` (`horaInicio`, `horaFin` son **FLOAT**:
  `7.0` = 07:00, `13.0` = 13:00). No hay concepto de día de la semana.
- `Employee.horas` existe y está en `NULL` para todos: es el campo destino del
  balance, hoy sin uso.
- La base de desarrollo `paginaobrasocialprueba` tiene 5 empleados de prueba,
  mientras los relojes tienen ~247 personas reales. **No existe hoy ninguna
  correspondencia entre ambos padrones.**

## Descomposición del proyecto

El pedido completo abarca seis subsistemas independientes. Esta spec cubre los
dos primeros; el resto tendrá su propio ciclo spec → plan → implementación.

| # | Subsistema | Depende de | Esta spec |
|---|---|---|---|
| 1 | Conector ISAPI + marcaciones crudas | — | **Sí** |
| 2 | `Employee.biometricoId` + UI de carga | 1 | **Sí** |
| 3 | Motor diario: pareo entrada/salida, tolerancia | 1, 2 | No |
| 4 | Advertencias por abuso (3/semana, 5/mes) | 3 | No |
| 5 | Balance de horas en `Employee.horas` | 3 | No |
| 6 | UI del perfil: acordeón mensual con barras | 3, 4, 5 | No |

## Objetivo

1. Traer automáticamente las marcaciones de ambos relojes a SQL Server.
2. Permitir que RRHH vincule cada empleado con su ID del reloj.
3. No modificar **nada** en los equipos: solo lectura.

## Diseño técnico

### Restricción dura: solo lectura

Requisito explícito del usuario: *"no quiero modificar nada del reloj, solo
absorber la información"*.

En ISAPI el verbo HTTP no indica si la operación escribe — las búsquedas usan
`POST` porque el filtro viaja en el cuerpo. Para que "solo lectura" sea una
garantía del código y no una convención, **todo acceso a los equipos pasa por un
único módulo** (`app/services/isapi_client.py`) que:

- acepta únicamente los verbos `GET` y `POST`; `PUT` y `DELETE` no están
  implementados;
- valida el path contra una **allowlist** cerrada y rechaza cualquier otro.

Allowlist (los únicos tres endpoints que el sistema puede invocar):

```
GET   /ISAPI/System/deviceInfo                  → health check
POST  /ISAPI/AccessControl/AcsEvent             → búsqueda de eventos (lee log)
POST  /ISAPI/AccessControl/UserInfo/Search      → búsqueda en el padrón (lee)
```

Endpoints deliberadamente **excluidos** (escriben en el equipo):
`UserInfo/Record`, `UserInfo/Modify`, `UserInfo/Delete`,
`RemoteControl/door/*`, `System/time`, `ClearEvent`, y cualquier PUT de
configuración.

Consecuencia intencional: nunca se llama a `ClearEvent`, así que la retención
del buffer de eventos del reloj sigue funcionando como hasta hoy, sin
interferencia del sync.

### Estrategia de sincronización: ventana con solape

`AcsEvent` filtra por `startTime`/`endTime`, **no** admite "serialNo mayor a".
Por eso el conector no usa un cursor de correlativo sino una ventana temporal:

```
ventana = [ RelojSync.ultimaSync − 10 min , ahora ]
```

El solape de 10 minutos cubre desfasajes de hora entre equipos y eventos que se
registran con retraso. Los duplicados que genera el solape los descarta el
índice único `(relojIp, serialNo)`: reprocesar una ventana es **idempotente** y
no tiene efecto secundario.

### Modelo de datos

```sql
Marcacion
  id            INT IDENTITY(1,1) PRIMARY KEY
  relojIp       NVARCHAR(20)   NOT NULL   -- '10.25.2.24'
  serialNo      BIGINT         NOT NULL   -- correlativo del equipo
  biometricoId  NVARCHAR(50)   NOT NULL   -- employeeNoString ('50')
  nombreReloj   NVARCHAR(100)  NULL       -- 'Zalazar Beatriz' (auditoría)
  fechaHora     DATETIME2      NOT NULL   -- hora local Argentina
  verifyMode    NVARCHAR(30)   NULL       -- 'fpOrface'
  createdAt     DATETIME2      NOT NULL
  CONSTRAINT UQ_Marcacion UNIQUE (relojIp, serialNo)

  INDEX IX_Marcacion_bio_fecha (biometricoId, fechaHora)

RelojSync
  relojIp       NVARCHAR(20)   PRIMARY KEY
  ultimaSync    DATETIME2      NULL
  ultimoError   NVARCHAR(500)  NULL
  activo        BIT            NOT NULL DEFAULT 1
```

Decisiones:

- **`serialNo` es por equipo**, no global: por eso la unicidad es compuesta con
  `relojIp`.
- **`fechaHora` se guarda en hora local de Argentina**, tal como la reporta el
  equipo. El subsistema 3 debe comparar contra `Horario.horaInicio = 7.0`, que
  también es hora local; convertir a UTC solo agregaría una fuente de errores
  de desfasaje.
- **`nombreReloj` se persiste** aunque sea redundante: permite auditar y
  detectar un `biometricoId` mal cargado sin volver a consultar el equipo.
- Las marcaciones se guardan **siempre**, incluso si el `biometricoId` no
  corresponde todavía a ningún empleado. Quedan huérfanas y aparecen
  retroactivamente cuando RRHH carga el vínculo, sin necesidad de resincronizar.

El DDL es idempotente (`IF OBJECT_ID(...) IS NULL` / `IF COL_LENGTH(...) IS
NULL`), cada sentencia en su propio batch seguido de `commit`, siguiendo el
patrón ya usado en el módulo de activos.

### Conector

Un job de **APScheduler** dentro del proceso FastAPI, cada **5 minutos**:

1. Para cada reloj `activo` en `RelojSync`:
   1. Calcula la ventana con solape.
   2. Pagina `AcsEvent` con `major=5` y `minor=38` **dentro de
      `AcsEventCond`**, para que el filtrado ocurra en el equipo y no viajen
      los eventos de puerta por la red (`maxResults` 100, avanzando
      `searchResultPosition` mientras `responseStatusStrg == "MORE"`).
   3. Descarta, ya del lado del cliente, cualquier evento sin
      `employeeNoString` — defensa por si el equipo ignorara el filtro.
   4. Inserta ignorando violaciones de la unicidad.
   5. Actualiza `ultimaSync` y limpia `ultimoError`.

**Los dos relojes se procesan de forma independiente**: si el `.25` no responde,
el `.24` igual sincroniza. El fallo se registra en `RelojSync.ultimoError`, no
propaga excepción al scheduler y se reintenta en el ciclo siguiente. Un equipo
caído nunca debe tumbar el job ni el backend.

Como el estado vive en `RelojSync` (tabla), un reinicio del backend no pierde
nada: el ciclo siguiente retoma desde `ultimaSync`.

**Riesgo conocido — reinicio del correlativo.** La idempotencia se apoya en que
`serialNo` sea siempre creciente dentro de un equipo. Si un reloj reiniciara su
numeración (reset de fábrica, o vuelta a cero del buffer), los eventos nuevos
colisionarían con los viejos y **se descartarían en silencio**. No se observó
ese comportamiento y el correlativo actual va por ~168.000, pero la
implementación debe registrar un warning cuando el `serialNo` máximo recibido de
un equipo sea *menor* que el último ya almacenado, para que la condición sea
detectable en lugar de manifestarse como marcaciones faltantes.

### Carga inicial

Endpoint ADMIN que trae el historial del **último mes** (~5.627 marcaciones).

Decisión explícita del usuario: **no importar historial más antiguo**, aunque los
equipos conserven desde 2025-08 / 2026-02. La carga inicial usa la misma ruta de
código que el job periódico, solo con una ventana más amplia, y es idempotente
por el índice único: repetirla no duplica.

### Vínculo de identidad

```sql
ALTER TABLE Employee ADD biometricoId NVARCHAR(50) NULL;
CREATE UNIQUE INDEX UX_Employee_biometricoId ON Employee(biometricoId)
  WHERE biometricoId IS NOT NULL;   -- índice filtrado: admite varios NULL
```

El índice filtrado impide que dos empleados compartan el mismo ID del reloj, que
sería un error silencioso grave (dos personas viendo las mismas marcaciones).

**UI:** campo de texto libre en el perfil del empleado, editable por RRHH.

**Confirmación por nombre:** al guardar, el backend consulta los relojes por ese
`employeeNo` vía `UserInfo/Search` y devuelve el nombre que tienen cargado, para
que RRHH lo verifique antes de confirmar. Si se carga `51` en lugar de `50`, la
pantalla responde *"51 = Zalazar Dante"* y el error queda a la vista. Es una
operación de **lectura**, compatible con la restricción de no modificar nada.
Si el ID no existe en ningún equipo, se advierte pero no se bloquea el guardado
(el equipo puede estar temporalmente inaccesible).

**Datos de prueba:** los `employeeNo` **50 a 55** se usan para vincular a los 5
empleados existentes en la base de desarrollo y validar el flujo end-to-end.

### Endpoints

| Método | Ruta | Permiso | Descripción |
|---|---|---|---|
| GET | `/relojes/estado` | ADMIN | Estado de sync de cada equipo |
| POST | `/relojes/sync` | ADMIN | Dispara una sincronización manual |
| POST | `/relojes/carga-inicial` | ADMIN | Trae el último mes |
| GET | `/relojes/usuario/{biometricoId}` | ADMIN | Nombre en el reloj (confirmación) |
| GET | `/marcaciones/{employee_id}` | Autenticado* | Marcaciones de un empleado |

\* Un empleado accede solo a las propias; ADMIN y RRHH acceden a cualquiera,
siguiendo el patrón de autorización ya usado en documentos de empleado.

### Seguridad

- Credenciales de los relojes en **`.env`** (`RELOJ_USER`, `RELOJ_PASS`,
  `RELOJ_IPS`), nunca en el código ni en este documento.
- SQL **100% parametrizado** con `text()` y diccionario de parámetros.
- RBAC: lecturas `require_any_auth` con chequeo de pertenencia; escrituras y
  operaciones sobre los equipos, `require_roles(ROLE_ADMIN)`.
- Timeout explícito en todas las llamadas HTTP a los relojes, para que un equipo
  colgado no bloquee el job.

### Manejo de errores

| Situación | Comportamiento |
|---|---|
| Reloj inaccesible | Se registra en `ultimoError`, el otro equipo continúa, reintenta al ciclo siguiente |
| Credenciales inválidas (401) | Igual que el anterior, con el mensaje diferenciado |
| Evento sin `employeeNoString` | Se descarta silenciosamente (es ruido de puerta) |
| `serialNo` ya existente | Se ignora la inserción (esperado por el solape) |
| `biometricoId` sin empleado | Se guarda igual, queda huérfana |
| Respuesta XML/JSON malformada | Se registra el error y se aborta solo ese equipo |

## Fuera de alcance

- Pareo entrada/salida y cálculo de cumplimiento (subsistema 3).
- Tolerancia de 15 minutos y su semántica sobre el balance (subsistema 3).
- Advertencias por abuso: 3 días en la semana, 5 en el mes (subsistema 4).
- Acumulación en `Employee.horas` y compensación a favor/en contra (subsistema 5).
- Acordeón mensual con barras en el perfil (subsistema 6).
- Cualquier escritura sobre los relojes: alta de personas, carga de huellas,
  cambio de hora, apertura de puerta.
- Notificaciones push del equipo (event notification): el diseño es de polling.
- Importación de historial anterior al último mes.
