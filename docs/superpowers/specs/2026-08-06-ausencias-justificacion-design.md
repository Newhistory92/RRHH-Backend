# Justificación de ausencias

**Fecha:** 2026-08-06
**Estado:** aprobado

## Problema

Hoy una ausencia resta la jornada completa del saldo y no hay forma de revertirlo
salvo cargando una licencia. El motor calcula `estado='ausente'` con
`horasRequeridas = horasTrabajo`, `horasTrabajadas = 0` y
`saldoDia = -horasTrabajo`.

Falta la segunda vía real: la persona faltó por enfermedad, presentó un parte
médico en papel, y RRHH no tiene dónde registrarlo. El día sigue restando horas
que nadie va a recuperar.

## Alcance

Una pestaña **Ausencias** en el detalle del empleado (vista de RRHH) con dos
modalidades de justificación:

1. **Por licencia** — ya funciona en el backend y no requiere código nuevo.
   `_dias_con_licencia` busca licencias con `status='Aprobada'` cuyo rango cubra
   el día, sin importar cuándo se cargaron. Una licencia retroactiva aprobada
   convierte el día de `ausente` a `licencia` en el próximo recálculo. Lo que
   falta es la UI que lo haga visible y accionable.

2. **Por parte médico** — no existe. Es lo que construye este spec.

Fuera de alcance: que el empleado cargue su propio parte médico, y que la
pestaña permita crear licencias (se cargan por su flujo normal, con sus
validaciones de tipo, antigüedad y saldo anual).

## Decisiones

| Decisión | Elección | Razón |
|---|---|---|
| Efecto en el saldo | Neutro, igual que licencia: 0 requeridas, saldo 0 | El día justificado no se debe ni se acumula |
| Reversibilidad | RRHH puede anular | El error de carga es el caso común |
| Ventana para justificar | 30 días hacia atrás | Fuerza a que los partes se presenten a tiempo |
| Vía licencia | Solo reconocer una existente | Una sola puerta de entrada a las licencias |
| Contenido de la lista | Ausencias pendientes y justificadas | Panorama del período |

## Arquitectura

El enfoque elegido trata la justificación como **un insumo más del recálculo**,
igual que feriados, licencias y correcciones manuales. Es el patrón que ya usa
`JornadaCorreccion`.

Se descartaron dos alternativas:

- **Crear una `License` de tipo "Parte médico"** — no exigiría tocar el motor,
  pero un parte médico de un día no es una licencia: arrastraría
  `Employee.status = 'Licencia'`, aparecería en el historial de licencias del
  legajo y quedaría sujeto al flujo de aprobación y a las reglas de tipo.

- **Columnas `justificada` / `documentoId` en `JornadaDiaria`** —
  `reemplazar_jornadas` borra y reinserta las filas del rango en cada recálculo,
  así que la justificación se perdería en el pase nocturno. Protegerla del
  borrado rompería la propiedad de que la tabla es derivada de sus insumos.

### Modelo de datos

```sql
CREATE TABLE JornadaJustificacion (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    employeeId     INT           NOT NULL,
    fecha          DATE          NOT NULL,
    documentoId    INT           NOT NULL,
    observacion    NVARCHAR(500) NULL,
    justificadoPor INT           NOT NULL,
    createdAt      DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaJustificacion UNIQUE (employeeId, fecha)
);
CREATE INDEX IX_JornadaJustificacion_employeeId
    ON JornadaJustificacion (employeeId, fecha);
```

`UNIQUE (employeeId, fecha)` — un día admite una sola justificación. Justificar
dos veces el mismo día es un upsert, no un duplicado.

**Sin columna `tipo`.** La vía licencia no escribe en esta tabla: se resuelve
contra `License`. La tabla es exclusivamente de partes médicos, y una columna
con un único valor posible sería especulativa. Si aparece otro justificativo
documentado, se agrega entonces.

`documentoId` es `NOT NULL`: el adjunto es obligatorio. Es un parte médico — el
papel es la razón de ser de la justificación. Apunta a `EmployeeDocument`, que
ya existe con `tipo`, `fileName`, `mimeType`, `fileData` (base64) y carga
restringida a RRHH. Las justificaciones usan `tipo='Parte médico'`.

`justificadoPor` guarda el `employeeId` de quien justifica, igual que
`JornadaCorreccion.corregidoPor`.

### Motor de cálculo

`app/services/asistencia_calc.py`:

- Constante nueva `ESTADO_JUSTIFICADA = "justificada"`, agregada a `__all__`.
- `EntradaDia` gana `justificada: bool = False`.
- El chequeo va **dentro** de la rama de ausencia:

```python
if entrada is None and salida is None:
    if e.justificada:
        return _resultado(e, ESTADO_JUSTIFICADA, 0.0, 0.0, 0.0)
    return _resultado(
        e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
        -e.horario.horasTrabajo,
    )
```

Ahí y no antes: si más tarde aparece una marcación por corrección manual, la
persona efectivamente trabajó y se le cuentan las horas — la justificación no se
las borra. La licencia se sigue evaluando antes, como hoy, porque cubre el día
aunque la persona haya pasado por la oficina. Un día con licencia y
justificación queda como `licencia`.

**La ventana de 30 días se valida al crear, nunca al aplicar.** El motor no la
conoce: si hay fila, justifica. Si el motor mirara la ventana, un saldo
histórico cambiaría solo con el paso del tiempo, sin que nadie hiciera nada.

### Persistencia

Módulo nuevo `app/database/asistencia_justificaciones.py`, siguiendo el patrón
de `asistencia_auditoria.py`:

```python
def ensure_tables(db: Session) -> None: ...

def upsert_justificacion(db: Session, employee_id: int, fecha: date,
                         documento_id: int, observacion: str | None,
                         justificado_por: int) -> int: ...

def borrar_justificacion(db: Session, employee_id: int, fecha: date) -> bool: ...

def dias_justificados(db: Session, employee_id: int,
                      desde: date, hasta: date) -> set[date]: ...

def justificaciones_de(db: Session, employee_id: int, desde: date,
                       hasta: date) -> dict[date, dict]: ...
```

`dias_justificados` alimenta el recálculo. `justificaciones_de` alimenta la UI y
trae los datos del documento (`fileName`, `mimeType`) por join con
`EmployeeDocument`, más el nombre de quien justificó.

`asistencia_recalc.py` suma `justificados = dias_justificados(...)` junto a los
demás insumos y pasa `justificada=d in justificados` al construir cada
`EntradaDia`.

### Validación

Función pura en el módulo de justificaciones, testeable sin `TestClient`:

```python
VENTANA_JUSTIFICACION_DIAS = 30

def validar_fecha_justificable(fecha: date, hoy: date) -> None:
    """Lanza ValueError si la fecha no se puede justificar."""
```

Rechaza fechas futuras y fechas anteriores a `hoy - 30 días`. La ruta traduce el
`ValueError` a HTTP 400.

### API

Router nuevo `app/routes/asistencia_ausencias.py`. `asistencia.py` ya carga
tablero, configuración, recálculo, correcciones y alertas; sumarle esto lo
empuja a un archivo que no se sostiene. Prefijo `/asistencia`, todo `SOLO_RRHH`.

**`GET /asistencia/empleado/{id}/ausencias?desde&hasta`**

```json
{
  "desde": "2026-01-01",
  "hasta": "2026-08-06",
  "ausencias": [
    {
      "fecha": "2026-07-15",
      "estado": "ausente",
      "horasPerdidas": 8.0,
      "puedeJustificar": true,
      "justificacion": null,
      "licenciaPendiente": {"id": 12, "type": "Enfermedad", "status": "Pendiente"}
    },
    {
      "fecha": "2026-06-03",
      "estado": "justificada",
      "horasPerdidas": 0.0,
      "puedeJustificar": false,
      "justificacion": {
        "documentoId": 5,
        "fileName": "parte-medico.pdf",
        "mimeType": "application/pdf",
        "observacion": "Reposo 24hs",
        "justificadoPor": "Ana Gómez",
        "createdAt": "2026-06-04T10:12:00"
      },
      "licenciaPendiente": null
    }
  ],
  "ventanaDias": 30
}
```

Lista los días con estado `ausente` o `justificada` del rango. Los días de
licencia no aparecen: nunca fueron un problema a resolver.

`licenciaPendiente` se completa cuando existe una `License` con
`status != 'Aprobada'` cuyo rango cubre la fecha. Es lo que hace accionable la
vía licencia: RRHH ve la ausencia, ve que hay una licencia sin aprobar que la
cubriría, la aprueba, y la ausencia se resuelve sola en el recálculo.

`puedeJustificar` refleja la ventana de 30 días, para que el frontend no ofrezca
un botón que el backend va a rechazar.

**`POST /asistencia/empleado/{id}/ausencias/{fecha}/justificar`**

Body: `{fileName, mimeType, fileData, observacion}`. Valida la ventana, crea el
`EmployeeDocument` con `tipo='Parte médico'`, hace el upsert de la justificación
y dispara `recalcular_anio(db, employee_id, fecha.year)`.

Acepta los días en estado `ausente` y `justificada`; el segundo caso reemplaza
el parte por uno corregido y marca el documento anterior como `activo = 0`. Es
lo que hace útil al upsert del `UNIQUE (employeeId, fecha)`.

Rechaza con 400 cualquier otro estado — justificar un día trabajado sería una
forma silenciosa de borrarle las horas a la persona.

El reemplazo también respeta la ventana de 30 días. Pasado ese plazo una
justificación se puede anular pero ya no corregir, que es la lectura estricta y
predecible de la regla.

**`DELETE /asistencia/empleado/{id}/ausencias/{fecha}/justificar`**

Borra la justificación, marca el documento como `activo = 0` y recalcula. 404 si
no había justificación.

## Frontend

`src/app/Componentes/TablaOperador/AusenciasEmpleadoTab.tsx`, más la pestaña
"Ausencias" en `Perfildetail.tsx` junto a las existentes.

- **Resumen**: ausencias pendientes, justificadas, y horas perdidas sin
  justificar.
- **Tabla**: fecha, día de la semana, estado, motivo, documento (link de
  descarga) y acciones.
- **Justificar** abre un modal con selector de archivo — convertido a base64
  como ya hace `DocumentsTab` — y campo de observación.
- **Anular** en las justificadas, con confirmación.
- El aviso de licencia pendiente aparece en la fila de la ausencia que cubriría,
  con el tipo y el estado de esa licencia.

Tipos nuevos en `Interfaces.ts`: `AusenciaEmpleado`, `JustificacionAusencia`,
`LicenciaPendiente`.

## Testing

El motor es puro y se testea sin base:

- Ausencia con justificación → estado `justificada`, requeridas 0, saldo 0.
- Ausencia sin justificación → sigue restando la jornada completa.
- Día con marcaciones y justificación → gana lo trabajado, la justificación no
  borra horas reales.
- Licencia y justificación el mismo día → gana `licencia`.
- Día no laborable con justificación → sigue sin generar fila.

`validar_fecha_justificable` se testea aparte: fecha de hoy, borde exacto de 30
días, 31 días atrás, fecha futura.

## Riesgos

**Recálculo en el request.** `POST /justificar` recalcula el año del empleado de
forma síncrona, igual que ya hace `POST /jornadas/{id}/correccion`. Es el
comportamiento establecido del módulo y el costo es de segundos para un
empleado.

**Documentos huérfanos.** Si el upsert falla después de crear el
`EmployeeDocument`, queda un documento sin justificación. Las dos operaciones
van en la misma transacción para evitarlo.
