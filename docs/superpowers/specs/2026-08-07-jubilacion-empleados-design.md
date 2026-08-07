# Jubilación de empleados

**Fecha:** 2026-08-07
**Estado:** aprobado

## Problema

No hay forma de registrar que una persona se jubiló. Hoy el legajo queda
`Activo` para siempre: sigue apareciendo en el tablero de RRHH, el recálculo
nocturno le genera una ausencia por cada día hábil que pasa, las vacaciones le
siguen acumulando por antigüedad y el usuario conserva el acceso al sistema.

Lo único que existe es la desactivación manual del usuario
(`PUT /users/{id}/activo`, solo admin), que corta el login pero no dice por qué
ni frena nada de lo demás.

## Alcance

Una condición laboral **Jubilado** con su fecha, cargada por RRHH desde el
detalle del empleado. La fecha dispara tres efectos: se corta el acceso, se
congela el cómputo de asistencia y vacaciones, y la persona pasa del tablero de
RRHH a un tablero propio de jubilados.

Fuera de alcance: otras causas de baja (renuncia, despido, fallecimiento). El
tablero nuevo es de jubilados y nada más; si más adelante aparecen otras bajas
se decide entonces si comparten tablero.

También fuera de alcance: liberar el `biometricoId` al jubilarse. El jubilado lo
conserva, así que si vuelve a fichar la marcación se guarda igual en
`Marcacion`. El dato crudo no se pierde y no hay que desvincular nada; lo que no
ocurre es que esa marcación se convierta en jornada.

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Relación con `tipoContrato` | Campo aparte, convive | Conserva si era planta o contratado, dato que hace falta para antigüedad y trámites |
| Fecha futura | Se permite; desactiva al llegar el día | RRHH conoce la fecha con anticipación y la carga cuando la sabe |
| Reversibilidad | RRHH borra la fecha y el empleado vuelve | El error de carga es el caso común y no debe exigir tocar la base |
| Población del tablero nuevo | Solo jubilados | Alcance acotado y verificable |
| Histórico | Se congela y queda consultable | Nada se borra, nada se cancela, el saldo queda clavado en su último valor |

## Arquitectura

La **fecha de jubilación es la fuente de verdad**. `Employee.status` y
`User.activo` son cache derivado que una única función mantiene.

Se descartaron dos alternativas:

- **Estado puramente derivado** (`fechaJubilacion <= hoy` calculado en cada
  consulta). Es más limpio conceptualmente y hace imposible la desincronización,
  pero obligaría a que el login joinee `CondicionLaboral` en cada request y a
  revisar toda consulta que hoy filtre empleados activos. Un olvido deja entrar
  a un jubilado al sistema: el modo de falla es silencioso y del lado inseguro.

- **Solo el estado, con la fecha como dato informativo.** No cumple el
  requisito de que la fecha dispare la desactivación por sí sola.

El enfoque elegido reusa el mecanismo que ya funciona. Si el reconciliador se
cae, alguien queda activo de más y se nota; en el enfoque derivado, una consulta
mal escrita deja pasar a un jubilado y nadie se entera.

### Modelo de datos

```sql
IF COL_LENGTH('CondicionLaboral','fechaJubilacion') IS NULL
ALTER TABLE CondicionLaboral ADD fechaJubilacion DATE NULL;
```

`NULL` significa "no jubilado". `tipoContrato` no se toca.

`Employee.status` gana el valor `'Jubilado'` junto a los existentes `'Activo'` y
`'Licencia'`. La columna no tiene constraint, así que el cambio es aditivo.

### La transición

Una sola función escribe las tres cosas, en una transacción:

```python
def aplicar_jubilacion(db: Session, employee_id: int,
                       fecha: Optional[date], hoy: date) -> bool:
    """
    Guarda la fecha y sincroniza el estado derivado. Devuelve True si el
    empleado quedo jubilado.

    fecha=None revierte: el empleado vuelve a Activo y recupera el acceso.
    """
```

- `fecha` cumplida (`<= hoy`) → `status = 'Jubilado'`, `User.activo = 0`
- `fecha` futura → se guarda, el empleado sigue operativo
- `fecha = None` → `status = 'Activo'`, `User.activo = 1`

La decisión de si una fecha ya corresponde vive en una función pura aparte,
testeable sin base:

```python
def jubilacion_cumplida(fecha: Optional[date], hoy: date) -> bool:
    """None nunca esta cumplida. Una fecha futura tampoco."""
    return fecha is not None and fecha <= hoy
```

### Reconciliación

Un job diario recorre a los que tienen fecha cumplida y todavía figuran activos,
y les aplica la misma función. No es un actuador especial: es la red que atrapa
las fechas futuras cuando llega su día, y el arranque tras una caída.

**Solo avanza.** El reconciliador nunca reactiva a nadie, ni siquiera si la
fecha dejó de estar cumplida — eso no puede pasar salvo que alguien edite la
fecha, y en ese caso el que decide es RRHH desde la interfaz. Reactivar es
siempre un acto explícito.

Es idempotente: correrlo dos veces da el mismo resultado que correrlo una.

### Efectos

**Login.** Cero código nuevo. `User.activo = 0` y `auth.py` ya responde 403
"Usuario inhabilitado".

**Asistencia.** La fecha entra como cota superior del rango en
`recalcular_anio`, simétrica a `fechaIngreso` que ya es la cota inferior por
empleado:

```python
hasta = min(date(anio, 12, 31), date.today())
jubilacion = emp.get("fechaJubilacion")
if jubilacion is not None:
    # datetime hereda de date: hay que chequear el tipo mas especifico primero
    jubilacion = jubilacion.date() if isinstance(jubilacion, datetime) else jubilacion
    hasta = min(hasta, jubilacion)
```

`_datos_empleado` suma `MAX(cl.fechaJubilacion)` al subquery que ya trae
`fechaIngreso`.

No hace falta excluir al jubilado de `recalcular_todos` ni escribir un caso
especial. Sigue procesándose, simplemente no genera días posteriores a su fecha:
el saldo se congela solo y el histórico queda intacto. Un recálculo posterior da
el mismo resultado, que es la propiedad que ya tiene el módulo.

**Vacaciones.** `calcular_dias_vacaciones` usa `date.today()` por dentro. Gana
un tercer parámetro opcional con la fecha de corte:

```python
def calcular_dias_vacaciones(tipo_contrato: str, fecha_ingreso,
                             fecha_corte: Optional[date] = None) -> int:
    ...
    today = fecha_corte or date.today()
```

Los llamadores pasan `fechaJubilacion` cuando existe. El cambio vuelve
determinista una función que hoy no se puede testear sin congelar el reloj.

Las licencias ya aprobadas no se tocan.

### API

**`PUT /rrhh/employee/{id}/jubilacion`** — RRHH y admin. Body:
`{"fechaJubilacion": "2026-08-07"}` o `{"fechaJubilacion": null}` para revertir.
Llama a `aplicar_jubilacion` y devuelve el estado resultante.

Va como endpoint propio y no como un campo más de
`PUT /rrhh/employee/{id}/condicion-laboral`. Aquel hace un UPDATE plano de datos
descriptivos; este dispara efectos sobre el acceso al sistema y sobre el cómputo
de asistencia. Meterlos en el mismo lugar haría que un guardado de rutina de la
condición laboral pudiera cortarle el acceso a alguien sin que se vea en el
código del llamador.

Si el frontend guarda ambas cosas en el mismo submit, hace dos llamadas.

**`GET /rrhh/jubilados`** — RRHH y admin. Los empleados con fecha cumplida, con
su fecha de jubilación y el saldo congelado.

El listado de RRHH existente suma `AND e.status <> 'Jubilado'` a su consulta.

## Frontend

**Detalle del empleado.** En la tarjeta de condición laboral, un campo de fecha
"Fecha de jubilación" junto a los que ya están. Con fecha cargada y cumplida, el
legajo muestra un aviso de que la persona está jubilada y desde cuándo.

**Tablero de jubilados.** Reusa la tabla del tablero de RRHH: misma grilla,
distinta fuente, más una columna de fecha de jubilación. Desde ahí se entra al
legajo completo, navegable en modo lectura.

## Pestañas del legajo

Bug aparte, sin relación con la jubilación. `Perfildetail.tsx` tiene ocho
pestañas en un `nav` con `flex space-x-8` y sin manejo de desborde, así que se
salen del layout. Se arregla con `overflow-x-auto` en el contenedor y bajando el
gap a `space-x-6`.

Va como tarea suelta del plan, no escondida dentro de la feature: es un fix de
una línea que se verifica mirando la pantalla, no con los tests de jubilación.

## Testing

Las dos funciones puras se testean sin base:

- `jubilacion_cumplida`: `None` da False, fecha futura da False, fecha de hoy da
  True, fecha pasada da True.
- `calcular_dias_vacaciones` con `fecha_corte`: la antigüedad se corta en la
  jubilación y no sigue creciendo con el paso del tiempo.

Sobre el recálculo, con las fixtures que ya existen:

- Jubilado a mitad de año: no se generan jornadas posteriores a su fecha.
- Sin fecha de jubilación: el rango no cambia respecto de hoy.
- Fecha de jubilación anterior a `fechaInicioModulo`: `desde > hasta` y no se
  genera ninguna jornada, sin error.

## Riesgos

**Desincronización entre la fecha y el estado derivado.** Es el costo del
enfoque elegido. Se acota con la función única de escritura y el reconciliador
diario, que además se auto-repara tras una caída. El modo de falla es visible
(alguien activo de más), no silencioso.

**`Employee.status = 'Jubilado'` en consultas que no lo esperan.** Cualquier
lugar que asuma que el status es `'Activo'` o `'Licencia'` va a ver un valor
nuevo. El plan debe revisar los filtros por status del frontend y el
`StatusBadge`, que hoy podría no tener color para el valor nuevo.
