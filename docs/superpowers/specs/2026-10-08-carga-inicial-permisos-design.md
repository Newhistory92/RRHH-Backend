# Carga inicial de horas de permiso ya consumidas

**Fecha:** 2026-10-08
**Estado:** aprobado
**Alcance:** cruza los dos repos (Backend_RRHH y RRHH)

## Problema

El cupo anual de horas de permiso ya funciona: sale de la jornada laboral
(`JornadaLaboral.horasPermisoAnual`), se consume cronológicamente, y agotado
convierte los permisos siguientes en horas a recuperar.

Lo que falta es el arranque. Un empleado que ya usó horas de permiso **antes de
que el sistema las registrara** —porque recién se lo da de alta, porque recién
se le asigna una jornada, o porque esas salidas se llevaban en papel— recibe hoy
el cupo del año entero. El sistema le regala las horas que en la realidad ya se
tomó.

Es el mismo problema que la carga inicial de saldos de licencias resolvió para
Vacaciones, pero aquel módulo está acotado explícitamente a esa categoría
(`CATEGORIA_ACUMULABLE` en `carga_inicial_licencias.py:35`) y trabaja en días,
no en horas. No cubre esto.

## Por qué no alcanza con cargar los permisos viejos a mano

La salida natural parece ser otra: dejar que RRHH registre los permisos que ya
se tomaron, con su fecha real, y que el motor los consuma como a cualquier otro.
Hoy no se puede, porque `create_permission` (`app/routes/rrhh.py:612`) tiene la
fecha clavada en el día de hoy:

```python
date = datetime.now().date()
```

Agregarle la fecha al modal parece resolverlo, y **no lo resuelve**. El motor
ignora a propósito los permisos de un día sin marcaciones
(`asistencia_calc.calcular_dia`):

```python
if entrada is None and salida is None:
    if e.justificada:
        return _resultado(e, ESTADO_JUSTIFICADA, 0.0, 0.0, 0.0)
    # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
    # marcaciones no descuentan nada, no hay presencia que ajustar.
    return _resultado(e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
                      -e.horario.horasTrabajo)
```

Ese `_resultado` no pasa `banco=`, así que la fila sale con `permisoBanco = 0` y
`calcular_anio` —que acumula con `consumido += r.permisoBanco`— suma cero. El
banco queda intacto.

Justamente los permisos viejos caen en días sin marcaciones: o son anteriores a
`fechaInicioModulo` (fuera del rango que el motor calcula), o el reloj no llega
hasta ahí. Peor todavía, un día sin marcaciones ya se cuenta como ausencia con
la jornada completa en contra, así que backdatear un permiso ahí no solo no
descontaría del cupo: dejaría a la persona peor.

Queda anotado porque la idea va a volver a aparecer. **La carga inicial tiene
que descontar sin depender del reloj**, y por eso es un valor guardado que
achica el banco, no una fila de `Permission`.

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Qué carga RRHH | Las horas **ya consumidas** | Son un hecho histórico que no se mueve; el cupo es configuración que RRHH puede editar |
| Años cargables | Solo el año calendario en curso | El banco no se arrastra, y los años cerrados no se recalculan nunca |
| Almacenamiento | Tabla propia, con el año estampado | Sin el año, el 1 de enero la carga vieja seguiría descontando contra el cupo nuevo |
| Cargas sucesivas | **Se suman**: cada carga es un asiento | Cargar 5 y después 10 son dos cargas reales que dan 15, no una corrección de la otra |
| Corregir un error | Borrando el asiento | Es la contrapartida de que se sumen: sin borrado, un 50 mal tipeado queda para siempre |
| Cómo entra al cálculo | Achica el banco antes de llamar al motor | El motor no cambia y descuenta siempre, haya marcaciones o no |
| Dónde carga RRHH | Botón en la pestaña "Historial de Permisos" | Es donde la persona ya está mirando; menos superficie que una pestaña nueva |
| Permiso | Uno nuevo, dedicado | Se apaga al terminar la migración sin tocar código ni sacar la pestaña |
| Qué ve el empleado | Línea propia en el cuadro de totales | Sumarlas dentro de "Usado" dejaría el total sin cerrar contra la lista de permisos |

### Por qué horas consumidas y no horas restantes

La carga inicial de licencias guarda lo que **queda** (`diasPendientes`), y lo
justifica: para Vacaciones el total se recalcula en cada consulta según la
antigüedad, así que guardar el consumo se desviaría solo al cruzar un tramo.

Acá el criterio se invierte, y a propósito. El cupo de permisos no se deriva de
nada: sale de `JornadaLaboral.horasPermisoAnual`, que RRHH edita a mano.
Guardando "le quedan 7", si alguien sube el cupo de 12 a 20 esas 7 se quedan
clavadas, cuando la persona usó 5 y debería tener 15. Guardando "ya usó 5", el
cupo nuevo se aplica solo.

Las horas consumidas no se mueven; el cupo sí. Se guarda lo que no se mueve.

### Por qué la tabla lleva el año

El alcance es solo el año en curso, pero la fila igual va estampada con su año.
Sin esa columna, el 1 de enero cada empleado con carga inicial arrastraría sus
horas del año anterior contra el cupo nuevo, y no habría con qué distinguirlo:
`cargadoEn` es un timestamp de auditoría, y usarlo como lógica de negocio se
rompe solo (RRHH podría cargar en diciembre datos del año siguiente, o corregir
en enero una carga del año anterior).

Con el año estampado, el recálculo del año siguiente no encuentra fila y usa el
cupo completo.

## Arquitectura

### Unidad 1 — Persistencia

> **Revisión 2026-10-08.** Esta unidad cambió después de la primera
> implementación. El diseño original guardaba **una sola fila** por empleado y
> año, y cada carga **reemplazaba** la anterior (upsert con `MERGE`). Probándolo,
> el usuario señaló que cargar 5 y después 10 tiene que dar **15**, no 10, y que
> el panel tiene que mostrar el historial de cada carga. Lo que sigue es el
> diseño vigente: **cada carga es un asiento**, el total es la suma, y un asiento
> equivocado se corrige borrándolo.

Tabla nueva en la base de RRHH:

```
ConsumoInicialPermiso
  id               INT IDENTITY(1,1) PRIMARY KEY
  employeeId       INT           NOT NULL
  anio             INT           NOT NULL
  horasConsumidas  DECIMAL(6,2)  NOT NULL   -- de ESTE asiento, no el total
  cargadoPor       INT           NULL       -- employeeId de quien cargó
  cargadoEn        DATETIME2     NOT NULL
```

**Sin clave única sobre `(employeeId, anio)`**: varios asientos del mismo
empleado y año es justamente el caso normal. El par sigue siendo el criterio de
agrupación para sumar, pero no de unicidad.

Módulo propio `app/database/consumo_inicial_permisos.py` con `ensure_table`, un
`INSERT` por asiento, un `DELETE` por `id` de asiento, una lectura del total
(suma de los asientos de ese empleado y año) y una lectura del listado de
asientos para el panel.

El `INSERT` reemplaza al `MERGE ... WITH (HOLDLOCK)` del diseño original. Ya no
hace falta: el `MERGE` existía para que la segunda carga de la misma clave
corrigiera a la primera en vez de fallar contra la clave única, y ahora la
segunda carga es un asiento más, legítimo. De paso desaparece la carrera que el
`HOLDLOCK` protegía: dos cargas simultáneas insertan dos asientos, que es el
resultado correcto.

La lectura del total devuelve **`float | None`**, con `None` para "no hay ningún
asiento". Es deliberado que no coalesca a 0 adentro: sus dos consumidores
necesitan cosas opuestas. El recálculo (Unidad 3) hace la aritmética y coalesce
con `or 0.0`, porque sin carga el banco es el cupo completo. El `GET` (Unidad 4)
necesita conservar la distinción, porque el panel de RRHH muestra el estado real
según corresponda. Si la lectura devolviera 0 para el caso sin asientos, esa
distinción se perdería en la capa de datos y no habría forma de recuperarla.

`cargadoPor` y `cargadoEn` son por asiento, y existen porque esto mueve horas
que se convierten en tiempo libre: tiene que ser trazable quién puso cada una.

Tres estados, no dos:

- **Sin asientos** → no se cargó nada; rige el cupo completo.
- **Asientos que suman 0** → se determinó que no usó ninguna.
- **Asientos que suman > 0** → ya usó esas horas.

La distinción entre "sin asientos" y "suma cero" es deliberada: no haber mirado
a un empleado y haber determinado que no usó nada son cosas distintas.

### Cómo se corrige una carga equivocada

Borrando el asiento. Es la contrapartida necesaria de que las cargas se sumen:
con reemplazo, un 50 mal tipeado se arreglaba escribiendo 5 encima; sumando, ese
50 quedaría para siempre si no hubiera forma de quitarlo.

Se descartó la alternativa de cargar asientos negativos para compensar: no
requiere endpoint de borrado y deja un log inmutable, pero obliga a RRHH a
razonar en negativos y llena el historial de líneas que son correcciones y no
cargas reales.

### Unidad 2 — El permiso

Uno nuevo en el catálogo de `app/permisos.py`:

```
"asistencia.cargaInicialPermisos":
    "Cargar horas de permiso ya consumidas previas al alta (transitorio)"
```

No se llama `permisos.cargaInicial` a propósito. En este repositorio la palabra
"permisos" ya significa tres cosas distintas —los de RBAC, la tabla
`Permission`, y las categorías de licencia—, y el catálogo de RBAC es el peor
lugar donde sumar esa ambigüedad.

Es transitorio como el de licencias: cuando termine la migración se le quita al
rol y el botón desaparece para todos, sin redeploy.

### Unidad 3 — El consumo inicial dentro del cálculo

En `app/services/asistencia_recalc.py`, `recalcular_anio` lee la fila del año
que está calculando y achica el banco antes de llamar al motor. Donde hoy hace:

```python
banco_anual = float(emp.get("horasPermisoAnual") or 0)
```

pasa a:

```python
consumo_inicial = consumo_de_empleado(db, employee_id, anio) or 0.0
banco_anual = max(float(emp.get("horasPermisoAnual") or 0) - consumo_inicial, 0.0)
```

El `or 0.0` es donde se coalesce el `None` de "no hay fila": acá la distinción
entre "sin carga" y "carga en cero" no cambia nada, las dos dejan el cupo
entero.

**`asistencia_calc.calcular_anio` no cambia.** Sigue recibiendo un número y
consumiéndolo cronológicamente; el motor no se entera de que existe una carga
inicial. Eso es lo que hace que descuente siempre, haya marcaciones o no, y lo
que mantiene al motor como función pura testeable sin base.

Si el consumo inicial supera al cupo, el banco arranca en 0 y todo permiso del
año pasa derecho a horas a recuperar. Es lo correcto: esa persona ya se pasó.

Cuesta una consulta extra por empleado y año en el recálculo. Es consistente con
cómo ya trabaja el módulo.

### Unidad 4 — Endpoints

Tres, todos bajo `require_permission("asistencia.cargaInicialPermisos")`, en
`app/routes/carga_inicial_permisos.py`.

**`GET /asistencia/carga-inicial-permisos/{employee_id}`** — devuelve el año en
curso, el cupo de la jornada como contexto, el **total** (`null` si no hay
ningún asiento, que es distinto de 0), y la **lista de asientos**, cada uno con
su `id`, `horasConsumidas`, `cargadoPor` y `cargadoEn`. El `id` es lo que el
panel necesita para poder borrar un asiento puntual.

**`POST /asistencia/carga-inicial-permisos/{employee_id}`** — agrega un asiento
al año en curso, registrando quién y cuándo, y dispara
`recalcular_anio(db, employee_id, anio)` sincrónico. Reemplaza al `PUT` del
diseño original: ya no se guarda "el valor", se agrega una carga.

**`DELETE /asistencia/carga-inicial-permisos/{employee_id}/{asiento_id}`** —
borra un asiento y dispara el mismo recálculo. Es la única forma de corregir una
carga equivocada. Valida que el asiento pertenezca a ese empleado antes de
borrarlo: sin eso, el `id` de la URL alcanzaría para borrar el asiento de
cualquier otro.

Las tres recalculan sincrónico porque son un solo empleado, a diferencia del
cambio de cupo de una jornada, que toca a toda su nómina y va en segundo plano.

Validación del `POST`: `horasConsumidas` no negativo, y tope de 2000 horas, el
mismo atajo contra el error de tipeo que ya usa el cupo. El tope aplica **por
asiento**, no al total: un total alto puede ser legítimamente la suma de varias
cargas reales, mientras que un solo asiento de más de 2000 horas solo puede ser
un error de tipeo. **Sin tope contra el cupo del empleado**: alguien puede haber
usado más horas de las que su cupo cubre, y eso tiene que poder cargarse.

El año no se recibe por parámetro en ningún endpoint: siempre es el año
calendario en curso. Es el único cargable, y aceptarlo del cliente solo abriría
la puerta a escribir años que después nadie recalcula.

### Unidad 5 — La pantalla de RRHH

Dentro de `PermissionHistoryTab` (la pestaña "Historial de Permisos" del
legajo), arriba del historial, un botón **"Cargar horas ya consumidas"** visible
solo con `asistencia.cargaInicialPermisos`.

Al tocarlo abre un panel con:

- El año en curso y el cupo de la jornada, como contexto de contra qué se
  descuenta.
- El **total acumulado** de los asientos, que es la cifra que efectivamente
  descuenta del cupo.
- La **lista de asientos**: cada línea con su fecha, quién lo cargó, las horas
  de ese asiento, y un botón para borrarlo. Es lo que hacía falta y no estaba:
  el panel anterior mostraba un número sin decir de dónde salía.
- Un campo para agregar un asiento nuevo, que **distingue vacío de cero**, según
  los tres estados de la Unidad 1.

Agregar llama al `POST` y borrar al `DELETE`; las dos cosas recalculan y
refrescan la lista sin cerrar el panel, para que RRHH pueda cargar varios
asientos de una pasada y ver el total actualizándose.

Cableado: hoy `PermissionHistoryTab` solo recibe `permisos`. Necesita también el
empleado (o su id) para saber de quién carga y guarda.

### Unidad 6 — Lo que ve el empleado

La carga inicial no deja filas en `Permission` ni en `JornadaDiaria`: son horas
que el sistema nunca registró. Si no se muestran, las cuentas de "Mis permisos"
no cierran.

`GET /asistencia/mis-permisos` suma una clave `consumoInicial` (número, 0 si no
hay fila para ese año), y `restante` pasa a ser:

```
restante = max(cupoAnual - consumoInicial - consumido, 0)
```

En la pantalla, el cuadro de totales suma una línea propia, **"Ya usadas antes
del registro"**, solo cuando `consumoInicial > 0` —una línea en cero sería
ruido—, separada de "Usado".

No se suman dentro de "Usado" a propósito: el empleado vería "Usado 7h" con una
lista de permisos que suma 2h, y no cerraría a la vista. Es el mismo problema
que ya se resolvió marcando los permisos oficiales, que tampoco consumen cupo.

Para años que no son el actual, `cupoAnual` y `restante` ya se devuelven como
`null` (el cupo guardado es el vigente, no uno por año). `consumoInicial` sigue
la misma regla: se muestra solo para el año en curso.

## Manejo de errores

- La carga valida antes de escribir y devuelve el motivo: horas negativas o por
  encima del tope.
- Cargar dos veces el mismo `(empleado, año)` agrega dos asientos y el total es
  la suma. Es el comportamiento buscado, no un duplicado a evitar.
- Borrar un asiento que no existe, o que pertenece a otro empleado, responde 404
  sin borrar nada. El chequeo de pertenencia importa: sin él, el `id` de la URL
  alcanzaría para borrarle un asiento a cualquier otra persona.
- Si el recálculo posterior al `POST` o al `DELETE` falla, el asiento ya quedó
  escrito (o borrado): el error se registra y el job nocturno lo corrige. Es el
  mismo contrato que ya tiene `create_permission`, que recalcula igual y no deja
  que una falla del recálculo tumbe el alta del permiso.
- Un empleado sin jornada asignada tiene cupo 0: la carga inicial se puede
  guardar igual (el banco ya arranca en 0 y queda en 0), y el panel muestra el
  cupo 0 como contexto para que RRHH vea que falta asignarle la jornada.

## Fuera de alcance

- Cargar años anteriores al en curso. El banco no se arrastra y los años
  cerrados no se recalculan.
- Agregarle fecha al modal de permiso de salida. Se evaluó y se descartó como
  solución a este problema (ver arriba); si alguna vez se quiere por otro
  motivo, es un trabajo aparte.
- Reconstruir el detalle de los permisos viejos. Cada asiento son horas
  agregadas, no una fila por salida con su horario.
- Editar un asiento ya cargado. Se borra y se carga de nuevo: un asiento es un
  hecho registrado, y permitir editarlo en el lugar perdería la trazabilidad de
  quién cargó qué sin dejar rastro.
- Tocar `asistencia_calc.calcular_anio`. El motor no se entera de esta feature.
- Prorratear el cupo para quien ingresa a mitad de año. Sigue fuera de alcance,
  como en el trabajo del cupo.

## Verificación

**Backend** (pytest, con el patrón `FakeSession`):

- El banco efectivo es `cupo - consumo_inicial`, y nunca negativo cuando el
  consumo inicial supera al cupo.
- Sin fila de carga inicial, el banco es el cupo completo.
- La carga inicial descuenta **aunque el día no tenga marcaciones**: es el caso
  que motiva toda la feature y el que distingue este camino del backdateo de
  permisos.
- **Dos asientos se suman**: cargar 5 y después 10 da un total de 15, no 10.
- Borrar un asiento baja el total en exactamente las horas de ese asiento, y
  deja los demás intactos.
- Borrar un asiento de otro empleado responde 404 y no borra nada.
- Los asientos de un año no afectan el cálculo de otro año.
- Sin asientos y con asientos que suman cero dan resultados distintos en el
  `GET` (`null` contra `0`).
- Validación: negativo y por encima de 2000 responden 400, **por asiento**.
- Los tres endpoints exigen `asistencia.cargaInicialPermisos`.
- `GET /asistencia/mis-permisos` devuelve `consumoInicial` y descuenta el
  `restante` con él.
- El excedente sobre el cupo cuenta como deuda y descuenta del saldo general
  (`saldo_acumulado`), y los tableros leen ese mismo saldo en vez de volver a
  sumar los días.

**Frontend** (no tiene runner de tests):

- `npx tsc --noEmit` sin errores nuevos. El repo arrastra ~27 previos no
  relacionados: el criterio es no agregar ninguno.
- En navegador: el botón aparece solo con el permiso; el panel trae lo ya
  cargado y distingue vacío de cero; guardar persiste y el saldo del empleado
  se mueve en consecuencia; "Mis permisos" muestra la línea nueva solo cuando
  hay carga inicial, y las cuatro cifras cierran entre sí.
