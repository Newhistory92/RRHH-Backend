# Extensión de tolerancia por día para quien vive fuera del anillo

**Fecha:** 2026-10-09
**Estado:** aprobado
**Alcance:** cruza los dos repos (Backend_RRHH y RRHH)

## Problema

Todos los empleados tienen 15 minutos de tolerancia de entrada y 15 de salida
(`AsistenciaConfig.toleranciaEntradaMin` / `toleranciaSalidaMin`). Es un valor
global y fijo: no hay forma de aflojarlo un día puntual.

Pero hay días en que el atraso no es responsabilidad de la persona —un
temporal, un paro de transporte, un corte de ruta— y el impacto no es parejo:
quien vive **fuera del anillo de Circunvalación** viaja mucho más y es el que
llega tarde, mientras que quien vive cerca llega igual que siempre.

Hoy RRHH no tiene herramienta para eso. O le descuenta las horas a gente que no
hizo nada malo, o le baja la tolerancia a todo el mundo de forma permanente.

## Qué se construye

Dos piezas que funcionan juntas:

1. **Un dato en el legajo**: un check "Fuera del anillo de Circunvalación" que
   marca a quién le aplican estas extensiones.
2. **Una acción en el tablero de Asistencia**: un botón "Extender tolerancia"
   donde RRHH elige una fecha y los minutos que rigen ese día, para los
   marcados.

Quien no está marcado mantiene siempre sus 15 minutos, haya o no extensión
cargada.

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Quién recibe la extensión | El **tildado** (vive fuera del anillo) | Es quien viaja más y a quien el día excepcional efectivamente le pega |
| Qué significa el valor cargado | **Reemplaza** los 15 min, no se suma | RRHH ve en pantalla el número final que va a regir, sin hacer cuentas |
| Entrada y salida | Dos valores, la **salida opcional** | El motivo típico es llegar tarde; aflojar la salida es otra concesión y se decide aparte |
| Días de extensión y abuso | **No marcan abuso** a quien la usó | Señalar a quien se amparó en un permiso que RRHH otorgó se contradice solo |
| Una extensión por fecha | Clave única por fecha | Es una propiedad del día, no un libro de asientos |
| Corregir una extensión | Borrarla y cargarla de nuevo | Un valor mal cargado le perdona horas a media planta: tiene que poder deshacerse |
| Quién edita el check | Solo `rrhh.gestionar` | Otorga un beneficio: si el empleado puede tocarlo, se lo autoconcede |

### El tooltip que el pedido original tenía al revés

El pedido pedía un tooltip que dijera que *"si está tildada esa opción, queda
fuera de excepciones horarias"*, pero también que la extensión aplicara a todos
**menos** a los que tienen el check sin marcar. Las dos cosas no pueden ser
ciertas a la vez. Se resolvió que **el tildado recibe la extensión**, así que el
tooltip dice:

> Tildado: este agente vive fuera del anillo y recibe las extensiones de
> tolerancia que RRHH otorgue para un día puntual. Sin tildar: mantiene siempre
> los 15 minutos de tolerancia.

Queda escrito acá porque la frase original va a volver a aparecer.

## Arquitectura

### Unidad 1 — El dato en el legajo

`Employee` suma `fueraAnilloCircunvalacion BIT NOT NULL DEFAULT 0`, con el
patrón `IF COL_LENGTH(...) IS NULL ALTER TABLE` que el repo ya usa para
`biometricoId` y `horasPermisoAnual`.

En el perfil del legajo, en la tarjeta "Datos Personales" (`ProfileTab` de
`DetailTables.tsx`), al lado del Domicilio. Esa tarjeta hoy es de **solo
lectura**: el check se guarda al tocarlo, con una llamada directa al `PUT`, sin
montarle un modo de edición a toda la tarjeta por un solo control.

Quien no tiene `rrhh.gestionar` lo ve **deshabilitado, no oculto**: que el
agente pueda ver cómo está cargado su propio dato es parte de que la decisión
sea auditable.

#### El campo no puede viajar por el camino de siempre

`PUT /employee/{employee_id}` (`app/routes/employee.py:570`) autoriza así:

```python
if current_user["employeeId"] != employee_id and not tiene_permiso(current_user["permisos"], "rrhh.gestionar"):
    raise HTTPException(status_code=403, ...)
```

Es decir: **el propio empleado puede editar su legajo**. Correcto para teléfono
o domicilio; inaceptable para este campo, que otorga un beneficio —cualquiera se
auto-tilda y se gana la tolerancia extendida.

El campo se suma a la lista blanca `employee_fields`, pero con un chequeo
propio: si viene en el payload y quien lo manda no tiene `rrhh.gestionar`,
responde **403**, en vez de ignorarlo en silencio. Ignorarlo sería peor: RRHH
tildaría el check, vería la tilde en pantalla y no se guardaría nada.

### Unidad 2 — La extensión

Tabla nueva en la base de RRHH:

```
ExtensionTolerancia
  id                    INT IDENTITY(1,1) PRIMARY KEY
  fecha                 DATE      NOT NULL   -- UNIQUE
  toleranciaEntradaMin  INT       NOT NULL
  toleranciaSalidaMin   INT       NULL       -- null = la salida queda en los 15 de config
  cargadoPor            INT       NULL
  cargadoEn             DATETIME2 NOT NULL
```

**Clave única por fecha.** Una extensión por día: es una propiedad del día, no
un libro de asientos que se acumula. Un segundo alta para la misma fecha se
rechaza pidiendo que borren la que está, en vez de pisar en silencio un valor
que le perdona horas a toda la planta que vive lejos.

`cargadoPor` y `cargadoEn` existen porque esto mueve horas que se convierten en
tiempo libre: tiene que ser trazable quién lo otorgó.

Módulo propio `app/database/extension_tolerancia.py`: `ensure_table`, listado,
alta y baja.

### Unidad 3 — Endpoints

Tres, todos bajo `require_permission("asistencia.gestionar")`, en un router
propio `app/routes/extension_tolerancia.py` —mismo criterio que
`carga_inicial_permisos.py`, para no seguir engordando `asistencia.py`.

- **`GET /asistencia/extensiones-tolerancia`** — todas las extensiones, la más
  nueva primero, con `id`, `fecha`, los dos valores, `cargadoPor` y `cargadoEn`.
- **`POST /asistencia/extensiones-tolerancia`** — alta.
- **`DELETE /asistencia/extensiones-tolerancia/{extension_id}`** — baja.

**Validaciones del alta**, tres y ninguna cosmética:

- **Fecha de hoy en adelante**, validado en el servidor y no solo con el `min`
  del calendario. El `min` de un input se saltea desde DevTools, y una extensión
  retroactiva reescribiría asistencia ya liquidada.
- **Cada valor tiene que ser mayor que la tolerancia vigente de su extremo.**
  Cargar `00:05` *recortaría* el margen de los que viven lejos, exactamente al
  revés de lo que el botón promete. La entrada se compara contra
  `toleranciaEntradaMin` y la salida —si viene— contra `toleranciaSalidaMin`,
  los dos leídos de la config al momento del alta. La regla vale para los dos
  extremos: una salida de `00:10` sería tan dañina como una entrada de `00:05`,
  y dejarla pasar solo porque el campo es opcional sería un agujero.
- **Tope de 480 minutos (8 h)** por valor, como atajo contra el error de tipeo:
  8 horas ya es una jornada entera y vacía el concepto de tolerancia; más que
  eso solo puede ser un dedazo. Vale igual para la salida si viene.

### Unidad 4 — La pantalla

El botón **"Extender tolerancia"** va en el encabezado de
`AsistenciaTablero.tsx`, junto a "Empezar desde hoy" y "Recalcular todo", que
son las otras dos acciones globales de asistencia.

Abre un modal con:

- Un calendario con `min` en la fecha de hoy.
- Un selector `HH:MM` para la **entrada** (obligatorio).
- Un selector `HH:MM` para la **salida** (opcional, con su propio valor).
- La **lista de extensiones ya cargadas** —fecha, los dos valores, quién la
  cargó— cada una con su botón de borrar.

Igual que el panel de carga inicial de permisos, el modal no se cierra al
cargar: la lista se refresca para que RRHH vea el resultado.

### Unidad 5 — Cómo entra al cálculo

**El motor no se entera de que esta feature existe.** `calcular_anio` suma un
parámetro:

```python
def calcular_anio(dias, tolerancias, banco_anual,
                  tolerancias_por_fecha: dict[date, Tolerancias] | None = None)
```

En el bucle, si el día tiene override lo usa; si no, usa el de siempre. El motor
no sabe qué es una extensión ni qué es el anillo de Circunvalación: solo sabe
*"este día rige esta tolerancia"*. Quien resuelve qué tolerancia corresponde a
cada día es `asistencia_recalc`, que es el que habla con la base.

Un empleado **sin** el check recibe el diccionario vacío y su cálculo queda
byte por byte igual que hoy.

#### El abuso se resuelve con los datos, no con una regla nueva

Para un día de extensión, el orquestador arma:

```python
Tolerancias(
    entradaMin=extension.toleranciaEntradaMin,
    salidaMin=extension.toleranciaSalidaMin or cfg["toleranciaSalidaMin"],
    estrictaEntradaMin=extension.toleranciaEntradaMin,
    estrictaSalidaMin=extension.toleranciaSalidaMin or cfg["toleranciaEstrictaSalidaMin"],
)
```

El margen estricto queda igualado al margen otorgado. Como la fórmula que ya
existe en `_ajustar_por_tolerancia` es

```python
abuso_entrada = uso_entrada and desvio_ent_seg > tol.estrictaEntradaMin * 60
```

y dentro de la tolerancia el desvío nunca supera un estricto que vale lo mismo,
**el abuso no se dispara**. No hace falta ningún `if es_dia_de_extension`: cae
por los datos. Esto importa porque esas marcas alimentan la alerta de *"uso
reiterado del margen"* que el agente ve en Mi Asistencia y el tablero de abusos
de RRHH; sin esto, un día de temporal con 30 minutos otorgados marcaría como
abuso a todo el que llegó 8:20.

### Unidad 6 — Cuándo hay que recalcular

El motor solo computa hasta hoy, así que un día futuro todavía no existe en
`JornadaDiaria`. Eso hace el recálculo mucho más barato de lo que parece:

| Acción | ¿Recalcula? |
|---|---|
| Alta para mañana o después | **No.** El día se calcula con la extensión puesta cuando llegue |
| Alta para hoy | Sí: hoy ya puede estar calculado |
| Baja de una extensión de hoy o pasada | Sí, el año de esa fecha |
| Baja de una extensión futura | No |

Cuando hace falta, es masivo pero acotado: **solo los empleados con el check**,
en segundo plano, con auditoría en `RecalculoLog` (`origen="extension_tolerancia"`),
espejando `recalcular_jornada` que ya existe. Se agrega
`recalcular_marcados_fuera_del_anillo(db, anio)` filtrando
`WHERE fueraAnilloCircunvalacion = 1 AND biometricoId IS NOT NULL`.

**Tildar o destildar el check también recalcula.** Si RRHH tilda a alguien
*después* de que pasó un día con extensión, sus días ya calculados quedaron sin
el beneficio; destildarlo deja el beneficio aplicado en días ya liquidados. El
`PUT` que cambia el campo dispara `recalcular_anio` del año en curso de ese
empleado —uno solo, sincrónico, como ya hace la carga inicial de permisos.

## Manejo de errores

- Las validaciones del alta cortan **antes** de escribir y devuelven el motivo:
  fecha pasada, valor menor o igual a la tolerancia vigente de ese extremo,
  valor por encima del tope.
- Alta para una fecha que ya tiene extensión: 409, pidiendo borrar la existente.
- Baja de una extensión que no existe: 404, sin recalcular nada.
- Si el recálculo posterior a un alta, una baja o un cambio del check falla, el
  dato ya quedó escrito: el error se registra y el job nocturno lo corrige. Es
  el mismo contrato que ya tienen `create_permission` y los endpoints de carga
  inicial de permisos —un 500 ahí le haría creer a RRHH que no se guardó cuando
  sí se guardó.

## Fuera de alcance

- Extensiones por departamento, oficina o empleado puntual. La extensión es
  global para todos los marcados.
- Extensiones retroactivas. Solo de hoy en adelante.
- Editar una extensión en el lugar. Se borra y se carga de nuevo.
- Cambiar los 15 minutos globales de `AsistenciaConfig`. Esta feature los deja
  como están y solo los pisa para un día y un subconjunto de gente.
- Avisarle al empleado que un día tuvo tolerancia extendida. El efecto se ve en
  su saldo; no se agrega notificación ni marca en la pantalla de Mi Asistencia.

## Verificación

**Backend** (pytest, con el patrón `FakeSession`):

- Un empleado **sin** el check calcula igual que hoy, con y sin extensiones
  cargadas en la base. Es la garantía de que la feature no toca a nadie más.
- Un empleado con el check y una extensión de 30 min: entrar 8:25 no descuenta
  horas **y no marca abuso**; entrar 8:35 sí descuenta.
- La salida sin cargar deja la tolerancia de salida en los 15 de config.
- Un día sin extensión, dentro de un año que tiene extensiones en otras fechas,
  usa la tolerancia normal.
- Las validaciones del alta responden 400 —incluida una **salida** menor que la
  tolerancia de salida vigente, no solo la entrada—, y la fecha duplicada 409.
- El alta para una fecha futura **no** dispara recálculo; la de hoy sí.
- `recalcular_marcados_fuera_del_anillo` filtra por el check y no barre la
  nómina entera.
- `PUT /employee/{id}` con el campo y sin `rrhh.gestionar` responde 403.
- Los tres endpoints exigen `asistencia.gestionar`.

**Frontend** (no tiene runner de tests):

- `npx tsc --noEmit` sin errores nuevos. El repo arrastra 27 previos: el
  criterio es no agregar ninguno.
- En navegador: el check aparece al lado del Domicilio, se guarda al tocarlo y
  persiste al recargar; se ve deshabilitado para quien no es RRHH; el tooltip
  dice lo acordado. El botón del tablero abre el modal, el calendario no deja
  elegir ayer, la salida se puede dejar vacía, la lista muestra lo cargado y el
  borrado la actualiza.
- De punta a punta: cargar una extensión para hoy de 00:30, confirmar que un
  agente marcado que entró 20 minutos tarde ese día deja de tener el descuento
  y no queda marcado como abuso, y que uno no marcado sigue con el descuento.
