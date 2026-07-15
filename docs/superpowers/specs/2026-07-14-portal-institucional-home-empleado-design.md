# Portal Institucional — Home del Empleado (subsistema 2)

## Contexto

Segundo subsistema del Portal de Comunicación Institucional. El subsistema 1 ([2026-07-14-portal-institucional-nucleo-publicaciones-design.md](2026-07-14-portal-institucional-nucleo-publicaciones-design.md), ya mergeado a `main`) creó el modelo de datos (`Publication`/`PublicationTarget`), el CRUD de autoría para HR/Admin, y `GET /publications/feed?employeeId=X` — el feed filtrado por organigrama que consume este subsistema.

Este subsistema construye la pantalla que ve el empleado: una nueva Home ("Inicio") que reemplaza la pantalla default tras login, muestra las publicaciones que le corresponden agrupadas visualmente, y dispara una notificación in-app cuando HR publica algo de inmediato.

Los 4 subsistemas del módulo completo: 1 (núcleo, hecho), **2 (este documento)**, 3 (editor rich-text + adjuntos), 4 (búsqueda avanzada + dashboard admin).

## Decisiones de diseño (confirmadas con el usuario)

1. **El portal reemplaza el default solo para el rol USER.** `getDefaultPage` hoy da: Admin → "admin", RRHH/Estadista → "estadísticas", USER → "editar-perfil". Se cambia únicamente la entrada de USER a "inicio"; Admin/RRHH/Estadista no se tocan.
2. **Accesible para todos los roles vía sidebar.** Se agrega "Inicio" a `PAGE_CONFIG` visible/accesible para los 4 roles — Admin/RRHH pueden entrar a verlo aunque no sea su default.
3. **Notificación solo en publicaciones inmediatas.** Si `fechaPublicacion` es NULL o ya pasó al crear la publicación, se notifica de inmediato a los empleados targeteados. Las publicaciones programadas para el futuro **no** disparan notificación cuando llega su fecha (sin cron, decisión ya tomada en el subsistema 1) — simplemente aparecen en el feed la próxima vez que el empleado lo consulta.
4. **Notificación reutiliza la tabla `Message` genérica** (la misma que ya alimenta la campanita de licencias/feedback/reubicación). Cero cambios en el frontend de notificaciones existente.
5. **Calendario institucional = solo feriados**, consumiendo `GET /licenses/feriados` (ya existe). No se mezcla con fechas de publicaciones.
6. **Sin "marcar como leído".** Explícitamente descartado por el usuario — no se pide.
7. **Sin favoritos.** Explícitamente descartado por el usuario — no se pide.
8. **Sidebar con 2 widgets, no 4.** El spec original pedía calendario + eventos + capacitaciones + vencimientos, pero el modelo de datos (subsistema 1) ya unificó capacitaciones dentro de "Evento Institucional" y no tiene un campo de "fecha límite" separado. Se simplifica a: Calendario (feriados) + Próximos eventos (categoría Evento Institucional, fecha futura).
9. **El detalle de una publicación se abre en un modal**, no en una pantalla/ruta propia — coherente con el patrón ya usado en Reubicación/Organigrama, y esta app no tiene ruteo real por ítem (todo es un switch de `page` en `page.tsx`).

## A. Backend — una sola extensión sobre código ya mergeado

Se extiende `POST /publications` (subsistema 1, `app/routes/publications.py`) para disparar notificaciones cuando la publicación es inmediata.

**Lógica agregada, dentro de la misma transacción del `POST`:**

```python
# Solo si la publicacion es inmediata (no borrador, fecha de publicacion nula o ya pasada)
if not es_borrador and (fecha_pub is None or fecha_pub <= now):
    destinatarios = db.execute(text("""
        SELECT DISTINCT e.id
        FROM Employee e
        INNER JOIN PublicationTarget t ON t.publicationId = :pubId
        WHERE t.scope = 'institucion'
           OR (t.scope = 'departamento' AND t.departmentId = e.departmentId)
           OR (t.scope = 'oficina' AND t.officeId = e.officeId)
    """), {"pubId": new_id}).mappings().all()

    msg_text = f"Nueva {categoria.lower()}: {titulo}"
    for r in destinatarios:
        db.execute(text("""
            INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
            VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
        """), {"empId": r["id"], "msg": msg_text, "now": now})
```

Mismo patrón exacto que usan `reubicacion.py`/`licenses.py`/`feedback` para notificar — ninguna tabla ni endpoint nuevo. `PUT /publications/{id}` **no** dispara notificaciones (editar no es "publicar"; evita re-notificar en cada corrección menor).

Para el calendario y "próximos eventos": **sin backend nuevo**. El calendario consume `GET /licenses/feriados` (ya existe, `require_any_auth`). "Próximos eventos" es un filtro client-side sobre la respuesta ya obtenida de `GET /publications/feed` (categoría = "Evento Institucional", `fechaPublicacion` futura).

## B. Frontend — routing

- `Page` (union type en `Interfas/Interfaces.ts`) gana el valor `"inicio"`.
- `PAGE_CONFIG` (`util/rbac.ts`) gana una entrada: `{id: "inicio", label: "Inicio", icon: "Home", section: "General", visibleFor: [ADMIN, USER, RRHH, ESTADISTA], accessibleFor: [ADMIN, USER, RRHH, ESTADISTA]}`.
- `getDefaultPage` (`util/rbac.ts`): se cambia únicamente `[ROLE_ID.USER]: "editar-perfil"` → `[ROLE_ID.USER]: "inicio"`.
- `page.tsx`: nuevo `case 'inicio': return <PortalInicio employeeData={employeeData} />;`, con el import correspondiente.

## C. Frontend — pantalla `screens/PortalInicio/Screen.tsx`

**Carga de datos:** un único `GET /publications/feed?employeeId={employeeData.id}` al montar (vía `apiClient`, patrón ya usado en todo el proyecto). Sin refetch automático — es de solo lectura, sin mutaciones desde esta pantalla.

**Agrupación client-side** del array de publicaciones recibido:
- Urgentes/fijadas: `prioridad === 'Urgente' || fijada === true` → banda destacada arriba de todo.
- Destacadas: `destacada === true` (excluyendo las ya mostradas como urgentes).
- Por categoría: el resto agrupado por `categoria`, mostrando solo las secciones (Circulares, Resoluciones, Mantenimiento y Reparaciones, etc.) que tengan al menos una publicación — sin headers de sección vacíos.
- Próximos eventos (sidebar): `categoria === 'Evento Institucional' && fechaPublicacion > ahora`, ordenado ascendente, top 5.

**Calendario (sidebar):** fetch independiente a `GET /licenses/feriados`; mini-calendario mensual con los feriados marcados.

**Detalle:** click en una card abre un `Dialog` (PrimeReact, patrón ya usado) con el contenido completo, metadatos (categoría, fecha, prioridad), y botón de cierre.

## D. Diseño visual (UI/UX)

Estilo **Bento Grid** (cards modulares, `rounded-2xl`, sombra suave, hover con leve elevación — 150-300ms) aplicado sobre los tokens semánticos ya existentes del proyecto ("Orgánico Cálido": `bg-card`, `bg-background`, `text-foreground`, `border-border`, `font-heading`) — **sin paleta nueva**.

**Layout** (2 columnas desktop, apilado en mobile):
- Banda de avisos urgentes arriba (si hay), con acento de color (`border-l-4 border-error` o similar).
- Columna principal (~2/3): secciones apiladas (Destacadas, luego por categoría), grid de cards dentro de cada una.
- Sidebar derecho (~1/3, sticky en desktop): widget Calendario + widget Próximos Eventos.

**Card de publicación** (reutilizada en todas las secciones): ícono de categoría (`lucide-react`, sin emojis) + título + resumen truncado (~2 líneas) + fecha relativa ("hace 2 días") + badge de prioridad + badge de categoría (nunca solo color, siempre con texto/ícono también).

**Estados:** skeleton mientras carga (no spinner bloqueante); sección sin publicaciones no se muestra; feed completamente vacío → estado vacío simple.

**Modal de detalle:** scrim 40-60% opacidad, cierre explícito.

**Dark mode:** ya soportado (`next-themes`); los tokens semánticos resuelven la variante oscura automáticamente, sin trabajo adicional.

## Manejo de errores

- `GET /publications/feed` falla → estado de error simple en la pantalla, sin reintento automático.
- `GET /licenses/feriados` falla → el widget de calendario se degrada (mes sin feriados marcados), no bloquea el resto del portal.
- El fan-out de notificaciones va en la misma transacción que crear la publicación (subsistema 1 ya lo hace transaccional): si falla la resolución de destinatarios, no queda la publicación creada a medias.

## Fuera de alcance

- Marcar como leído — descartado explícitamente (decisión 6).
- Favoritos — descartado explícitamente (decisión 7).
- Notificación al llegar la fecha de una publicación programada — requiere cron, fuera de alcance (decisión 3).
- Navegación directa desde la notificación a la publicación (deep link) — la notificación solo muestra texto, igual que hoy (decisión 4).
- Widgets de "capacitaciones" y "vencimientos institucionales" como entidades separadas — unificados/descartados (decisión 8).
- Editor rich-text, adjuntos, búsqueda avanzada, dashboard admin — subsistemas 3 y 4.

## Testing

Sin suite automatizada — verificación manual:

1. `POST /publications` con fecha inmediata inserta un `Message` por cada empleado targeteado; probar los 3 scopes (institución, departamento con herencia a sus oficinas, oficina puntual).
2. `POST /publications` con fecha futura (programada) no inserta ningún `Message`.
3. `PUT /publications/{id}` (editar) no dispara notificaciones nuevas.
4. Loguearse como USER → aterriza en "Inicio" (ya no "Editar Perfil").
5. Loguearse como Admin/RRHH → sigue aterrizando en su pantalla de siempre; "Inicio" aparece disponible en el sidebar.
6. El feed se agrupa correctamente (urgentes arriba, destacadas, por categoría) y respeta el targeting — un empleado no ve publicaciones que no le corresponden.
7. Click en una card abre el modal con el contenido completo; el cierre funciona.
8. Widget de calendario muestra los feriados; "Próximos eventos" solo muestra categoría Evento Institucional con fecha futura, ordenados.
9. Dark mode: toda la pantalla (cards, badges, calendario, modal) se ve correctamente en ambos modos.
10. Responsive: en mobile el sidebar pasa debajo del contenido principal.
11. La notificación de una publicación nueva aparece en la campanita existente sin haber tocado su código.
