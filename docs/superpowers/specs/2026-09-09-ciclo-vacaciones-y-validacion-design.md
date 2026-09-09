# Ciclo de vacaciones, configuracion sin año y validacion de saldo

**Fecha:** 2026-09-09
**Estado:** aprobado para planificar

## Objetivo

Que las vacaciones de un año se habiliten recien el 1 de octubre de ese año,
que los dos endpoints que responden "cuantos dias tiene disponibles" usen el
mismo criterio de año vigente, que la configuracion de licencias describa
dias base por contrato sin arrastrar un año, y que el backend deje de aceptar
pedidos que superan el saldo.

## Por que existe

Hoy conviven dos definiciones distintas de "año en curso" en el mismo archivo:

- `GET /licenses/tipos-disponibles` usa `today.year` — el año calendario, sin
  corte de octubre. Es el endpoint que **realmente limita** cuantos dias puede
  pedir el empleado: el tope del selector de fechas sale de aca.
- `GET /licenses/saldos` usa `today.year if today.month >= 10 else today.year - 1`.
  Es la pantalla de consulta, y su corte de octubre gobierna la ventana de tres
  años y cual vence.

Es decir que la regla que la institucion aplica -las vacaciones de un año se
habilitan el 1 de octubre- esta implementada a medias: en el endpoint que
muestra, no en el que autoriza. Desde el 1 de enero un empleado puede pedir
las vacaciones del año que recien empieza.

Esta inconsistencia ya habia quedado anotada como hallazgo menor en la
revision de la rama anterior, sin resolver.

### Lo que se encontro al revisar

Tres cosas mas aparecieron al mirar el circuito completo, y las tres entran en
esta spec:

**La ventana Oct-Abr existe y esta muerta.** `create_license_request` valida
que las vacaciones se tomen entre el 1 de octubre y el 30 de abril, pero el
`raise HTTPException` esta adentro de un `try` cuyo `except Exception: pass`
lo atrapa -- `HTTPException` hereda de `Exception`. La validacion se dispara y
se traga a si misma; nunca bloqueo nada. Es la misma familia de defecto que se
corrigio en `/licenses/aplicar`, donde un `except` demasiado ancho convertia
los 404 y 409 en 500.

Nadie lo noto porque el frontend aplica la misma regla del lado del cliente.
Lo que esta abierto es la API, no la pantalla.

**El backend no valida saldo.** `create_license_request` chequea genero,
antiguedad, rol y que nadie pida a nombre de otro, pero nunca compara los dias
pedidos contra los disponibles. El tope es una cortesia del navegador: un POST
directo con noventa dias de vacaciones entra sin objecion.

**La configuracion arrastra un año que no le corresponde.**
`ConfiguracionLicencias` tiene una columna `anio`, y solo existen filas de
2026. De ahi salen dos problemas encadenados: `/tipos-disponibles` no encuentra
configuracion para un año anterior, y `/saldos` **deriva su ventana multi-año
de esas filas**, con lo cual un año sin fila directamente no aparece. El parche
que hoy sostiene eso -`saldos_sin_configuracion`- existe solo por esta causa.

## Decisiones tomadas

| Decision | Elegido | Por que |
|---|---|---|
| Alcance de la regla de octubre | Solo Vacaciones | Es la unica categoria acumulable, con ciclo real. Las anuales sin arrastre dejarian al empleado sin dias los primeros nueve meses |
| Antes del 1 de octubre | Rige el saldo del año anterior | Da continuidad, y es el criterio que `/saldos` ya aplica |
| Configuracion | Sin año: dias base por contrato y categoria | El año es logica, no dato. Elimina la dependencia de que exista la fila del año correcto |
| Columna `anio` | Se deja de usar ahora, se borra despues | Un DROP es irreversible: si algo quedo leyendola, con este orden se detecta sin perder nada |
| Ventana Oct-Abr | Revivirla | Ya esta escrita y decidida; lo unico que falta es que funcione |
| Validacion de saldo | Aplica a todos, RRHH incluido | Criterio parejo, sin excepciones por rol |
| Tope acumulado de 3 años | Fuera de alcance, va a Spec 2 | Arrastra repartir el consumo entre años, que es el cambio mas delicado del circuito |

### Por que el tope acumulado no entra aca

El pedido original incluia que el tope fuera el saldo acumulado de la ventana
de tres años, y no el de un solo año. Se separo por una razon concreta.

Los dos lugares que registran consumo lo hacen contra un unico año, derivado
de la fecha de inicio (`int(startDate[:4])`). El reparto por año que calcula el
frontend nunca se envia: el payload manda `tiposLicencia: {}` vacio y el
reparto sobrevive solo como texto en la nota al supervisor.

Con el tope acumulado eso se vuelve explotable: alguien con diez dias de 2024 y
veinte de 2025 pide los treinta en noviembre de 2026, el consumo se registra
entero contra 2026, y al recalcular 2024 y 2025 siguen intactos. El acumulado
vuelve a dar treinta y los mismos dias se pueden pedir otra vez, sin limite.

Hoy ese defecto esta contenido por accidente, porque el tope de un solo año no
deja llegar hasta ahi. Subir el tope al acumulado le saca ese freno, asi que
las dos cosas tienen que viajar juntas -- en Spec 2.

## Arquitectura

### Unidad 1 — El ciclo como funcion pura

`ciclo_vacaciones(hoy: date) -> int` en `app/services/saldo_licencias.py`,
junto a `anios_de_carga`. Devuelve `hoy.year` cuando el mes es octubre o
posterior, y `hoy.year - 1` cuando no.

Es la expresion que `/saldos` ya tiene escrita a mano. Sacarla a una funcion
con nombre es lo que impide que los dos endpoints vuelvan a divergir: hoy
divergen justamente porque la regla esta duplicada como expresion suelta en un
lado y ausente en el otro.

### Unidad 2 — La configuracion pierde el año

`ConfiguracionLicencias` pasa a significar dias base por `(tipo, categoria)`,
sin dimension temporal.

El codigo deja de leer y de escribir `anio` en los ocho puntos que hoy la
tocan: la consulta de `/tipos-disponibles`, el GET/POST/PUT de
`/licenses/configuracion`, `seed_configs_si_faltan`, el bloque de expiracion,
la consulta de `/saldos`, las tres consultas de `carga_inicial_licencias.py` y
la consulta vestigial de `rrhh.py` que busca configuraciones por `licenseId`.

**La columna se deja en la tabla, sin uso.** El `DROP COLUMN` es un paso
posterior y deliberado, una vez confirmado en el servidor que nada quedo
leyendola.

Se verifico que la migracion es limpia: no hay restriccion unica que incluya
`anio`, y agrupando por `(tipo, categoria)` no aparece ningun duplicado, asi
que quitar el año no colisiona filas.

Tres consecuencias:

- **`/saldos` genera su ventana de años por codigo**, a partir de
  `ciclo_vacaciones` y el ancho de tres años, en vez de derivarla de las filas
  de configuracion.
- **`saldos_sin_configuracion` se elimina.** Existe unicamente para que un
  saldo cargado en un año sin fila de configuracion no quede invisible. Sin
  años en la configuracion, todos los años de la ventana tienen base por
  construccion y el caso desaparece.
- **`seed_configs_si_faltan` se elimina**, por la misma razon: no hay nada por
  año que sembrar.

Sobre el bloque de expiracion: hoy busca la configuracion del año que vence
(`c.anio = :expAnio`) para saber cuantos dias correspondian. Sin año, esa
consulta devuelve la base del contrato, que es el mismo numero que
correspondia entonces. El año sigue importando para el consumo y para el saldo
inicial de ese año -- lo que deja de tener año es la base, no el calculo.

### Unidad 3 — Las vacaciones atadas al ciclo

En `/licenses/tipos-disponibles`, la categoria Vacaciones pasa a resolverse
contra `ciclo_vacaciones(hoy)`: su consumo se suma de ese año y la clave del
saldo inicial pasa a ser `(ciclo, "Vacaciones")`.

Las demas categorias siguen resolviendose contra el año calendario, sin
cambios. La regla es solo de vacaciones.

El orden de precedencia se conserva tal como esta hoy: la configuracion manda
mientras no sea cero, el calculo por antiguedad rellena cuando esta en cero, y
el saldo inicial cargado a mano pisa a los dos. Lo unico que cambia es sobre
que año se aplica.

### Unidad 4 — Revivir la ventana Oct-Abr

Sacar el `raise HTTPException` de adentro del `try` en
`create_license_request`, para que el `except Exception: pass` no lo atrape.

Para un usuario normal no cambia nada, porque el frontend ya bloquea esas
fechas. Lo que se cierra es el camino directo a la API.

### Unidad 5 — Validacion de saldo

Extraer el calculo por categoria que hoy vive dentro de `/tipos-disponibles` a
una funcion reutilizable, y que `create_license_request` la use para rechazar
cuando los dias pedidos superan los disponibles.

Reusar en vez de reescribir es deliberado: una segunda implementacion del mismo
calculo es precisamente lo que produjo la divergencia que esta spec corrige.
Ademas garantiza que el backend valide exactamente contra el mismo numero que
la pantalla ofrecio.

La validacion **no distingue por rol**: si RRHH carga una licencia a nombre de
otro empleado, tambien queda sujeta al saldo.

### Unidad 6 — La pantalla de configuracion

La pantalla de Configuracion → Licencias pierde la columna Año, su orden, su
inclusion en la busqueda, el campo del formulario y el valor por defecto al
crear una fila. El modal de ayuda deja de filtrar por `?anio=`, que pasa a no
tener sentido.

El agrupado por categoria del modal se conserva: distintos contratos siguen
teniendo topes distintos para la misma categoria, y esa es justamente la
dimension que la tabla mantiene.

## Manejo de errores

El rechazo por saldo devuelve 400 nombrando la categoria y cuantos dias hay
disponibles, en vez de un mensaje generico: quien lo recibe tiene que poder
corregir el pedido sin adivinar.

La ventana Oct-Abr devuelve su 400 con el motivo que ya tiene escrito, que
hasta hoy nunca llego a salir.

## Testing

Las piezas con decision se aislan como funciones puras y los endpoints siguen
el patron `FakeSession` que ya usa la suite.

- `ciclo_vacaciones` contra los bordes exactos: 30 de septiembre devuelve el
  año anterior, 1 de octubre devuelve el año en curso, 31 de diciembre el año
  en curso, 1 de enero el anterior. El borde es la regla entera, asi que se
  prueba el dia de cada lado y no un mes cualquiera.
- `/tipos-disponibles` consulta el año que corresponde segun la fecha, y las
  categorias que no son vacaciones siguen resolviendose contra el año
  calendario.
- El tope fijo de configuracion sigue rigiendo sobre el calculo por antiguedad
  ahora que no hay año: es la decision que motivo el fix anterior y no puede
  perderse al quitar la dimension.
- La ventana Oct-Abr **efectivamente corta**. Es el test que habria atrapado el
  `except` desde el principio, asi que se escribe contra el endpoint y no
  contra una funcion interna: a nivel unitario el defecto era invisible.
- La validacion de saldo rechaza excederse, permite pedir exactamente el
  limite, y tambien alcanza a RRHH.

`FakeSession` no ejecuta SQL real, asi que los nombres de columna se verifican
aparte contra `INFORMATION_SCHEMA` al escribir las consultas.

## Precondicion operativa

Como la validacion de saldo alcanza tambien a RRHH, una categoria mal
configurada -en cero- bloquea a todos, sin salida por el costado. Revisar los
valores de las 21 categorias deja de ser prolijidad y pasa a ser condicion para
que esto entre sin cortar el circuito de licencias.

Es configuracion, no desarrollo, pero tiene que estar hecho antes del deploy.

## Fuera de alcance

- **Tope acumulado de la ventana de tres años y reparto del consumo entre
  años.** Van juntos en Spec 2, por lo explicado arriba.
- **El vencimiento automatico corre de forma perezosa.** Solo se dispara cuando
  alguien abre `GET /licenses/saldos` de ese empleado; no hay ningun job en el
  scheduler. Ademas procesa un unico año por corrida (`ciclo - 3`), asi que si
  durante un año nadie abrio esa pantalla, ese vencimiento se saltea y no se
  recupera nunca. Queda documentado, sin resolver.
- **La acumulacion exclusiva de vacaciones no esta garantizada por codigo.** El
  vencimiento esta escrito a mano contra `'vacaciones'`, asi que si alguien
  cargara configuracion de otra categoria para un año anterior, ese saldo no
  venceria jamas. Hoy no se nota porque no existen filas viejas.
- **El `DROP COLUMN` de `anio`.** Paso posterior y deliberado.

## Restricciones vigentes

- **Nunca escribir en la base ObraSocial.** Todo acceso a
  `[ObraSocial].[dbo].*` es de solo lectura.
- Cero IDs de rol hardcodeados. La autorizacion siempre via
  `require_permission(...)`.
- Comentarios y docstrings en español sin tildes, como el resto del
  repositorio.
