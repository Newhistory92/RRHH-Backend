# Cupo anual de permisos por jornada, y la pantalla "Mis permisos"

**Fecha:** 2026-10-07
**Estado:** aprobado
**Alcance:** cruza los dos repos (Backend_RRHH y RRHH)

## Problema

El sistema ya descuenta los permisos de un cupo anual de horas libres, y ya
convierte en horas a recuperar lo que se pide una vez agotado ese cupo. Lo hace
`calcular_anio` en `app/services/asistencia_calc.py`, recorriendo el año en
orden cronológico. Faltan dos cosas.

La primera es que el cupo está clavado en el código: `BANCO_PERMISO_ANUAL_HORAS
= 12.0`. Son 12 horas para todos, y RRHH no tiene forma de cambiarlo ni de
diferenciar a quien trabaja media jornada de quien trabaja ocho horas.

La segunda es que la persona no lo ve. Hoy el empleado abre "Mi asistencia" y
encuentra un saldo acumulado que ya tiene adentro las horas de permiso que se
le pasaron del cupo, sin ninguna pista de que existe un cupo, de cuánto era, ni
de cuánto le queda. El único lugar del producto donde aparece la cifra es un
texto del modal de RRHH que dice "el cupo de 12 h anuales"
(`LicenseModal.tsx:249`), que el propio empleado nunca ve.

## Qué ya funciona y no se toca

Vale dejarlo escrito porque es la mitad del trabajo que no hay que hacer:

- `calcular_anio` arrastra el consumo del banco día a día, en orden
  cronológico. Es el único lugar donde el banco cambia de valor.
- `permisoBanco` son las horas que el cupo cubrió; `permisoDeuda`, las que se
  pasaron. Ambas se persisten por día en `JornadaDiaria`.
- Las horas cubiertas por el cupo bajan las horas requeridas del día, así que
  el saldo queda neutro. Las que se pasaron no, y por eso restan.
- El permiso marcado como **oficial** es neutro en los dos sentidos: no consume
  cupo y no genera deuda. En el cálculo del día se resta de lo trabajado y de
  lo requerido, así que se cancela.
- Hay tests que cubren todo lo anterior.

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Alcance del cupo | Por jornada laboral | Es donde RRHH ya configura las jornadas, y `Employee.jornadaId` ya las vincula; permite distinguir media jornada de jornada completa |
| Empleado sin jornada | Cupo 0 | Hace visible el dato faltante en vez de regalarle un cupo por omisión |
| Al cambiar el cupo | Recalcular en segundo plano | El cupo se edita rara vez; el patrón ya existe en `POST /asistencia/recalcular` y la pantalla de configuración no se cuelga |
| Años afectados | Solo el año en curso | Un permiso de un año cerrado ya se liquidó contra el cupo que regía entonces |
| Dónde lo ve el empleado | Pantalla propia "Mis permisos" | Un cuadro suelto dentro de Asistencia no daba lugar al detalle por año |
| Imputación por permiso | No se muestra | Repartir el total del día entre sus permisos duplicaría la regla cronológica que hoy vive en un solo lugar |

## Consecuencia asumida: cupo 0 cambia la regla para quien no tiene jornada

Hoy todos tienen 12 horas, incluida la gente sin `jornadaId`. Con esta decisión
esa gente pasa a cupo 0: **todo permiso regular les genera horas a recuperar
desde el primer minuto**. Es deliberado, para que el legajo incompleto se note
en vez de quedar tapado por un valor por omisión.

La válvula que les queda es el flag "oficial", que sigue siendo neutro. RRHH
tiene que saberlo, porque es la única forma de darle un permiso sin consecuencia
a alguien que todavía no tiene jornada asignada.

## Arquitectura

### El cupo como dato

`JornadaLaboral` suma la columna `horasPermisoAnual DECIMAL(6,2) NOT NULL
DEFAULT 12`. El default es lo que hace que la migración no le cambie el cupo a
nadie: las jornadas que ya existen arrancan con el valor que regía. El tipo
admite fracciones de hora y deja techo de sobra para el tope de validación de
2000.

`JornadaLaboral` es una tabla preexistente: no se crea desde este repo, así que
el `ALTER` sigue el patrón de `ALTER_EMPLOYEE_BIOMETRICO_SQL` en
`app/database/marcaciones.py` — `IF COL_LENGTH('JornadaLaboral',
'horasPermisoAnual') IS NULL ALTER TABLE ...`, en su propio batch con su commit.

Vive en `app/database/asistencia.py::ensure_tables`, que ya hospeda los `ALTER`
de `AsistenciaConfig` y `JornadaDiaria`. Eso obliga a un cambio chico en
`app/routes/schedules.py`: hoy no llama a ningún `ensure`, y pasa a llamar a ese
`ensure_tables` antes de leer o escribir la columna nueva, para no depender de
que alguien haya entrado antes a una pantalla de asistencia.

### El motor deja de saber el número

`calcular_anio` pasa a recibir el cupo como parámetro (`banco_anual: float`),
igual que hoy recibe `Tolerancias`. `BANCO_PERMISO_ANUAL_HORAS` deja de ser la
fuente de verdad.

`asistencia_recalc.recalcular_anio` resuelve el cupo del empleado
(`Employee.jornadaId → JornadaLaboral.horasPermisoAnual`) y se lo pasa; si el
empleado no tiene jornada, pasa `0.0`.

Esto conserva la propiedad que el módulo declara en su docstring: el motor es
una función pura que se testea sin base ni fixtures.

### La configuración

`GET /schedules/regimes` y `POST /schedules/jornadas` suman
`horasPermisoAnual`.

Validación: se rechaza negativo y se rechaza por encima de 2000 horas. El techo
no es una regla de negocio sino un atajo contra el error de tipeo, que acá
cuesta caro: cargar 120 en vez de 12 regala diez veces el cupo y no lo nota
nadie.

En el frontend, el modal de Jornada Laboral de la pestaña "Régimen Horario"
(`ConfiguracionLicencias/Screen.tsx`) pasa de dos inputs a tres: nombre, horas
por día, y horas de permiso al año. La tarjeta de cada jornada muestra el cupo
junto a las horas por día.

### El recálculo

Se agrega `recalcular_jornada(db, jornada_id, anio)` en
`app/services/asistencia_recalc.py`, hermana de `recalcular_todos`: mismo
patrón de auditoría en `RecalculoLog` (`abrir_recalculo` / `cerrar_recalculo`,
con `origen="cupo_permiso"`) y misma garantía de que un empleado que falla se
registra y no aborta el resto de la corrida. Lo único que cambia es el filtro:
`WHERE jornadaId = :jornada AND biometricoId IS NOT NULL`.

El handler de `POST /schedules/jornadas` lo dispara con `BackgroundTasks` y su
propia `SessionLocal()` — la sesión del request se cierra cuando el handler
retorna, y ese detalle ya está resuelto así en `POST /asistencia/recalcular`.
La corrida queda visible en `GET /asistencia/recalculos`.

Dos recortes deliberados:

- **Solo se recalcula si el cupo cambió.** Renombrar una jornada no dispara una
  pasada masiva al vacío. Crear una jornada tampoco: todavía no tiene ningún
  empleado asignado, así que no hay nada que recalcular.
- **Solo el año en curso.** Cambiar el cupo no reescribe años cerrados. Si
  alguna vez hiciera falta, `recalcular_historia` ya existe para hacerlo a mano.

Si el recálculo en segundo plano falla, el cupo ya quedó guardado: el error va a
`RecalculoLog` y al log del servidor, y el job nocturno lo corrige igual. Es el
mismo contrato que ya tiene el recálculo manual.

### El endpoint de la pantalla

`GET /asistencia/mis-permisos?anio=YYYY`, en `app/routes/asistencia.py`,
siguiendo la regla que ese router declara en su docstring: el empleado sale del
token y nunca se acepta un `employeeId` por parámetro, así que nadie puede leer
permisos ajenos.

Devuelve:

- `cupoAnual` — de la jornada del empleado; `0` si no tiene jornada asignada.
- `consumido` y `deuda` — suma de `permisoBanco` y `permisoDeuda` de
  `JornadaDiaria` en ese año. **El endpoint no vuelve a aplicar la regla
  cronológica**: lee lo que el motor ya resolvió, que es la fuente única de
  verdad.
- `restante` — `max(cupoAnual - consumido, 0)`.
- `permisos` — las filas de `Permission` de ese año: fecha, hora de salida, hora
  de retorno, horas y el flag `oficial`.
- `aniosConDatos` — para el selector de año: los años que tienen permisos, más
  el año en curso, para que el actual aparezca aunque esté vacío.
  `saldo_licencias.anios_de_vacaciones_con_datos` ya resuelve esto mismo para
  vacaciones y es el patrón a espejar.

Errores: usuario sin legajo vinculado responde 403 con el mismo mensaje que ya
usa `GET /asistencia/mi`. Un año sin datos responde el año pedido con la lista
vacía, no 404: la pantalla tiene que poder decir "no pediste permisos ese año".

### La pantalla

Pantalla nueva "Mis permisos": selector de año arriba, el cuadro de totales
(cupo, consumido, restante, y horas pasadas a recuperar), y debajo la tabla de
permisos del año.

Los permisos oficiales se marcan de forma visible. Tienen que distinguirse:
como no consumen cupo ni generan deuda, si se vieran iguales a los regulares
las cuentas no cerrarían a la vista.

Dos estados que se redactan, no se dejan en cero pelado:

- **Sin jornada asignada** (cupo 0): el cuadro no dice "te quedan 0 horas". Dice
  que no tiene jornada laboral asignada, que por eso cada permiso regular se le
  cuenta como horas a recuperar, y que lo consulte con RRHH. Si no, la pantalla
  se lee como un error del sistema.
- **Sin permisos ese año**: mensaje explícito, con el cupo completo visible.

### Navegación

El tipo `Page` suma `"mis-permisos"`, y entra en `PAGE_CONFIG` en la sección
"Agente" con permiso `asistencia.propia`.

Se reutiliza ese permiso en vez de crear uno nuevo: los permisos propios son
parte de la asistencia propia, y un permiso nuevo habría que sembrarlo en
`app/database/permissions.py` y asignarlo a cada rol sin ganar nada a cambio.

En celular, `AppHeader` suma la entrada en el menú del avatar, espejando el
bloque de Reubicación que ya existe ahí.

**No lleva `ocultaSiTienePermiso`**, a diferencia de `documentos`. Si se
escondiera del sidebar para los roles de gestión, esa gente se quedaría sin
ningún lugar donde ver *sus propios* permisos: la entrada del menú del avatar
está condicionada a tener navegación simple, que RRHH y ADMIN no tienen. Les
suma una línea al menú, pero les conserva el acceso.

### El texto que queda mintiendo

`LicenseModal.tsx:249` dice hoy: "Un permiso oficial no consume el cupo de 12 h
anuales ni genera horas a recuperar". Con el cupo por jornada esa cifra deja de
ser cierta. Pasa a decirlo sin el número, o con el del empleado si está
disponible en ese punto.

## Fuera de alcance

- Prorratear el cupo para quien ingresa o se va a mitad de año. Hoy el cupo es
  anual y entero, y esto no lo cambia.
- Mostrar, permiso por permiso, cuánto cubrió el cupo y cuánto pasó a deuda.
- Reescribir años cerrados al cambiar el cupo.
- Una vista de RRHH de los permisos de terceros: ya los ve en el perfil del
  empleado.
- Tocar la lógica del motor de cálculo más allá de recibir el cupo por
  parámetro.

## Verificación

**Backend** (pytest, con el patrón `FakeSession`):

- `calcular_anio` con el cupo por parámetro: cupo 0 (todo permiso regular es
  deuda desde el primer minuto), cupo que se agota a mitad de año, y el caso
  oficial que no consume nada. El test que ya existe en
  `test_asistencia_calc.py:281` llama `calcular_anio(dias, TOL)` y hay que
  actualizarlo: es el único call site de la función pura.
- `recalcular_anio` leyendo el cupo de la jornada, y `0.0` cuando `jornadaId` es
  null. Los fixtures de `test_dias_excluidos_por_baja.py:72` hoy devuelven
  `horaInicio`/`horaFin`/`horasTrabajo` en la fila de `Employee`; hay que
  sumarles la columna nueva.
- `recalcular_jornada` filtrando por `jornadaId`, y no tumbando la corrida
  cuando un empleado falla.
- La validación de `horasPermisoAnual`: negativo y por encima de 2000.
- `GET /asistencia/mis-permisos` sin legajo vinculado responde 403.

**Frontend** (no tiene runner de tests):

- `npx tsc --noEmit` sin errores nuevos. El repo arrastra ~27 previos no
  relacionados: el criterio es no agregar ninguno.
- En navegador: el tercer input de la jornada guarda y se relee; la pantalla
  "Mis permisos" muestra los totales y la lista, cambia de año, distingue los
  oficiales, y resuelve bien los dos estados vacíos; la entrada aparece en el
  sidebar en escritorio y en el menú del avatar en celular.
- Prueba de punta a punta: cambiar el cupo de una jornada, esperar el recálculo
  de fondo, y confirmar que el saldo y los totales de un empleado de esa jornada
  se movieron en consecuencia.
