# Baja de empleados

**Fecha:** 2026-09-17
**Estado:** aprobado
**Reemplaza:** `2026-08-07-jubilacion-empleados-design.md`

## Problema

No hay forma de registrar que una persona dejó de trabajar en la institución,
salvo que el motivo sea la jubilación. Para una renuncia, un despido o un fin de
contrato, lo único disponible es la desactivación de la cuenta desde el panel de
ADMIN (`PUT /users/{id}/activo`), que corta el login de golpe: no dice por qué
se fue, no frena el cómputo de asistencia ni de vacaciones, y —lo que más
molesta— le saca a la persona el acceso a su propio legajo.

Eso último es el requisito que ordena todo este diseño. La institución necesita
que quien ya no trabaja **conserve la cuenta y pueda seguir consultando la
documentación de su legajo**, y nada más que eso.

La jubilación, además, quedó a mitad de camino: su spec se declaró
explícitamente acotada a ese motivo ("si más adelante aparecen otras bajas se
decide entonces si comparten tablero"). Es ahora. Y en la práctica nunca se
usó: al momento de escribir esto, cero empleados tienen `fechaJubilacion`
cargada, así que unificar no arrastra migración de datos.

## Alcance

Un registro de bajas con motivo, cargado por RRHH desde el detalle del
empleado. La baja **no toca el login**: la persona sigue entrando con su usuario
y contraseña, pero sus permisos quedan recortados a uno solo,
`documentos.propios`, así que lo único que existe para ella es la pantalla de
Documentos.

La jubilación pasa a ser un motivo de baja más y adopta ese comportamiento: deja
de bloquear la cuenta. El tablero de jubilados se absorbe en un tablero de bajas
filtrable por motivo.

**Fuera de alcance:**

- El bloqueo de cuenta del panel de ADMIN, que sigue existiendo sin cambios para
  lo que es un caso distinto (cortarle el acceso a alguien, con o sin baja).
- Borrado o anonimización de datos. Nada se borra: el historial de licencias
  aprobadas, la asistencia y los documentos quedan intactos, que es justamente
  el punto del legajo.
- Descontar el período de baja de la antigüedad de un reincorporado. La
  antigüedad sigue contándose desde `fechaIngreso` sin restar el hueco.
- Liberar el `biometricoId` al darse de baja. Igual que decidió la spec de
  jubilación: la marcación cruda se sigue guardando, lo que no ocurre es que se
  convierta en jornada.

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Relación con jubilación | Es un motivo de baja más | Un solo mecanismo, un solo tablero; la jubilación deja de bloquear la cuenta |
| Qué conserva el dado de baja | Solo `documentos.propios` | El requisito es el legajo a la vista y nada más: sin inicio, CV, asistencia, licencias ni feedback |
| Catálogo de motivos | Lista fija en código | Estadísticas sobre categorías estables y comparables; agregar uno es una línea |
| Fecha de efecto | Pasada, hoy o futura | Permite registrar bajas retroactivas y cargar renuncias con preaviso |
| Reversibilidad | Dos acciones distintas | Corregir borra la fila (error de carga, no ensucia estadísticas); reincorporar la cierra con fecha y la deja en el historial |
| Riesgo de lockout | Se rechaza la baja del último ADMIN | Es el único escenario que obligaría a arreglar la base a mano |
| Licencias pendientes | Se cancelan con la baja | La persona ya no puede verlas y quedarían para siempre en la cola del supervisor |
| Fecha de corte de cómputos | La fecha de baja, cualquier motivo | Una sola fuente; y hoy a quien renunció le seguirían creciendo vacaciones y saldo para siempre |

### Catálogo de motivos

```python
MOTIVOS_DE_BAJA = (
    "Jubilación",
    "Renuncia",
    "Despido",
    "Fin de contrato",
    "Fallecimiento",
    "Traslado a otro organismo",
    "Abandono de cargo",
)
```

Un motivo fuera del catálogo se rechaza con 400. No hay campo libre: las
observaciones son para el detalle (número de resolución, por ejemplo), no para
inventar categorías.

## Arquitectura

### Modelo de datos

```sql
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'EmployeeBaja' AND xtype = 'U'
)
BEGIN
    CREATE TABLE EmployeeBaja (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        employeeId     INT            NOT NULL,
        motivo         NVARCHAR(50)   NOT NULL,
        fechaBaja      DATE           NOT NULL,
        observaciones  NVARCHAR(500)  NULL,
        fechaReingreso DATE           NULL,
        registradaPor  INT            NULL,
        createdAt      DATETIME2      NOT NULL
    );
    CREATE INDEX IX_EmployeeBaja_employeeId ON EmployeeBaja (employeeId);
END
```

DDL idempotente con `ensure_table`, como el resto del proyecto.

Una fila por evento de baja: una persona puede irse, volver e irse de nuevo, y
las tres cosas quedan registradas. `fechaReingreso NULL` es "sigue de baja".
`registradaPor` es el `employeeId` de quien la cargó y sale del token, no del
payload: mueve accesos, así que la firma tiene que ser de quien efectivamente lo
hizo. Admite `NULL` porque una cuenta puede no tener empleado asociado (el caso
del ADMIN de sistema), no porque el dato sea opcional.

Se **elimina** `CondicionLaboral.fechaJubilacion`. Todo lo que hoy la lee pasa a
leer la fecha de baja vigente.

### "Está de baja" se calcula, no se almacena

La regla vive en una función pura, testeable sin base:

```python
def baja_vigente(bajas: list[dict], hoy: date) -> dict | None:
    """
    La baja que hoy tiene efecto, o None.

    Una baja con fechaReingreso ya no tiene efecto: la persona volvio. Una
    fechaBaja futura tampoco: se carga cuando se sabe y la persona sigue
    trabajando hasta ese dia.
    """
```

#### Por qué acá el estado derivado sí, cuando la spec de jubilación lo rechazó

La spec de jubilación evaluó un estado puramente derivado y lo descartó con un
argumento concreto: obligaría al login a joinear `CondicionLaboral` en cada
request y a auditar toda consulta que filtre empleados activos, y un olvido
"deja pasar a un jubilado y nadie se entera" — falla silenciosa y del lado
inseguro.

Ese argumento no aplica acá, y vale la pena dejar escrito por qué:

- **El eje ya no es el acceso, son los permisos.** La baja no bloquea el login
  —es el requisito—, así que no hay ninguna consulta de "empleados activos" que
  auditar. Lo que se recorta son los permisos, y esos ya se resuelven contra la
  base en **cada** request, en un único lugar (`permisos_de_rol` en
  `app/auth_middleware.py`). No hay superficie dispersa donde olvidarse.
- **El modo de falla se invierte.** Con el estado derivado, el corte de accesos
  no puede desincronizarse: se calcula con la fecha en el momento de usarlo. Una
  baja cargada con fecha futura pasa a tener efecto sola a la medianoche, sin
  depender de que ningún job haya corrido. Si el job diario se cae, el acceso se
  recorta igual.
- **El historial lo exige.** Corregir y reincorporar son acciones distintas con
  fechas propias; una columna de estado no las puede representar.

`Employee.status` sigue recibiendo `'Baja'`, pero degradado a **caché cosmético**
para los listados que ya muestran esa columna. No es fuente de verdad de nada.

### El recorte de permisos

Una única función decide los permisos efectivos, y la usan los dos lugares que
hoy los calculan por separado:

```python
def permisos_efectivos(db: Session, role_id: int | None,
                       employee_id: int | None) -> set[str]:
    """
    Los permisos con los que realmente opera alguien.

    Un empleado de baja conserva la cuenta pero solo su legajo: el recorte
    ignora el rol, incluido el comodin de ADMIN.
    """
```

- `app/auth_middleware.py` en `get_current_user`, que ya trae el `employeeId` en
  la misma consulta a `[User]` — el recorte no agrega un round-trip.
- `app/routes/auth.py` en la respuesta del login, que el frontend guarda en
  `localStorage`. **Los dos son obligatorios:** si solo se recortara el
  middleware, el dado de baja recibiría el menú completo al loguearse y lo vería
  hasta la próxima recarga.

El recorte devuelve exactamente `{"documentos.propios"}` y es lo último que se
aplica, así que no hay rol que lo esquive.

### Efectos al aplicarse la baja

Una sola función, en una transacción:

1. Inserta la fila en `EmployeeBaja`.
2. Cancela las solicitudes de licencia en `'Pendiente'` y
   `'Pendiente Siguiente Aprobación'` de esa persona.
3. Escribe `Employee.status = 'Baja'`.
4. **No toca `User.activo`.** Es toda la diferencia con el bloqueo de ADMIN.

Corregir y reincorporar hacen el camino inverso sobre el caché:
`Employee.status` vuelve a `'Activo'`. Las solicitudes canceladas **no** se
resucitan —quedan rechazadas con su observación— porque volver a la cola del
supervisor una licencia que se rechazó semanas antes sería más confuso que
pedirla de nuevo.

Cancelar es pasar la solicitud a `'Rechazada'` con una observación que dice que
fue por la baja, en vez de agregar un estado `'Cancelada'`. El tipo
`LicenseStatus` del frontend es una unión cerrada de cuatro valores y sumarle uno
obliga a tocar cada badge, color y filtro: mucha superficie dispersa para una
distinción que la observación ya deja registrada.

Como parte de este cambio, `_sync_employee_status` (`app/routes/licenses.py`)
gana un guard para no pisar un estado terminal. Hoy reescribe `Employee.status` a
`'Activo'` o `'Licencia'` en cada aprobación de licencia, sin mirar lo que había:
ya le pisa el `'Jubilado'` al jubilado, y sin el guard heredaríamos el mismo bug
con `'Baja'`.

### Reconciliación

El job diario que hoy aplica jubilaciones se reconvierte: recorre las bajas con
fecha recién cumplida y les aplica los **efectos colaterales** (caché de estado y
cancelación de pendientes). El corte de accesos no lo necesita, porque se
calcula. Sigue siendo idempotente y sigue solo avanzando: nunca reactiva a nadie
—reactivar es siempre un acto explícito de RRHH.

### La fecha de corte, generalizada

Dos cálculos usan hoy la fecha de jubilación como cota superior. Los dos pasan a
usar la fecha de la baja vigente, sea cual sea el motivo:

- `calcular_dias_vacaciones(tipo_contrato, fecha_ingreso, fecha_corte)` en
  `app/routes/licenses.py`. El parámetro ya se llama `fecha_corte` y ya está
  documentado como genérico: solo cambia de dónde sale el valor.
- `rango_de_calculo(anio, inicio_modulo, fecha_ingreso, fecha_baja, hoy)` en
  `app/services/asistencia_recalc.py`, que es lo que congela el saldo. El
  parámetro se renombra de `fecha_jubilacion` a `fecha_baja`.

Conceptualmente no cambia nada —ambas funciones ya tratan la fecha como cota
superior— pero el congelamiento deja de ser un privilegio del jubilado: hoy a
quien renunció le seguirían creciendo tanto las vacaciones como el saldo de
asistencia para siempre.

## Endpoints

Todos bajo `rrhh.gestionar`, el permiso que ya gobierna el módulo.

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/rrhh/employee/{id}/baja` | Registra la baja: `motivo`, `fechaBaja`, `observaciones` |
| `DELETE` | `/rrhh/employee/{id}/baja` | Corrige: borra la fila y la persona vuelve a operar normal |
| `PUT` | `/rrhh/employee/{id}/reincorporacion` | Cierra la baja con `fechaReingreso` y la deja en el historial |
| `GET` | `/rrhh/bajas` | El tablero: lista de bajas y conteo por motivo |

Validaciones del `POST`: motivo dentro del catálogo; una sola baja abierta por
persona a la vez; y el rechazo del último ADMIN, con un mensaje que explique qué
hacer (bajarle el rol primero desde el panel de administración). La
`fechaReingreso` no puede ser anterior a la `fechaBaja`.

Se **eliminan** `PUT /rrhh/employee/{id}/jubilacion` y `GET /rrhh/jubilados`. La
unificación los reemplaza y el frontend es nuestro, así que no quedan shims de
compatibilidad.

## Frontend

**La acción.** Hoy la jubilación es un campo de fecha dentro del formulario de
Condición Laboral, que se guarda junto con todo lo demás. Para la baja esa es la
afordancia equivocada: corta accesos y cancela solicitudes, así que va como
acción propia y explícita en el detalle del empleado, con modal de confirmación
—motivo, fecha, observaciones— que enumera qué va a pasar. Si la persona ya está
de baja, el mismo lugar ofrece corregir y reincorporar.

**El tablero.** `JubiladosTable.tsx` se convierte en `BajasTable.tsx`, colgado
de la pantalla RRHH donde está hoy. Cada fila es una baja: nombre, DNI,
departamento, oficina, motivo, fecha de baja, antigüedad al irse y saldo final
congelado (esa columna ya la calcula la consulta de jubilados y se conserva).

La lista es histórica y muestra los tres estados posibles de una baja, cada uno
identificable de un vistazo: **vigente**, **reincorporada** (con su fecha de
reingreso) y **programada** —fecha futura, todavía sin efecto—. Las programadas
tienen que estar: son el único lugar donde RRHH puede ver y corregir una baja
que cargó con preaviso antes de que llegue el día. El desglose por motivo cuenta
solo las bajas que ya ocurrieron —vigentes y reincorporadas—, porque una baja
programada todavía puede cancelarse y contarla inflaría la estadística. Además,
búsqueda por nombre o DNI y filtro por motivo.

**El menú de perfil.** Los cinco ítems del dropdown en
`src/app/Componentes/Shell/AppHeader.tsx` están hardcodeados sin chequear
permisos. Hay que gatearlos con `tienePermiso`, o al dado de baja le quedarían
visibles "Editar Perfil", "Mi Asistencia", "Licencias" y "Encuesta" sin llevar a
ninguna parte. El sidebar y `getDefaultPage` no necesitan cambios: ya leen de los
permisos, y con uno solo la persona aterriza directo en Documentos.

## Testing

**Funciones puras, sin base:**

- `baja_vigente`: sin bajas, con fecha futura, con fecha cumplida, con
  reingreso cargado, y con varias bajas donde solo una está abierta.
- El recorte de `permisos_efectivos`: que un ADMIN con comodín termine en
  `{documentos.propios}`, y que sin baja vigente los permisos pasen intactos.
- La antigüedad al irse que muestra el tablero.

**Con `FakeSession`,** el doble que ya usa el proyecto:

- El `POST` rechaza el motivo fuera de catálogo, la segunda baja abierta y al
  último ADMIN.
- La baja cancela las pendientes y deja el historial aprobado intacto.
- La reincorporación rechaza una fecha anterior a la baja.

**Los 14 tests de `test_jubilacion.py` se conservan** como tests del corte por
baja: la regla es la misma y son casi todos renombres. Se suman los de
reincorporación y corrección.
