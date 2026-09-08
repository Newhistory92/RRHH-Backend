"""
Carga inicial de saldos de licencias. TRANSITORIO.

Existe para poblar el saldo pendiente de los empleados que ya venian
trabajando cuando el sistema se puso en marcha: sin esto su consumo da cero y
el sistema les otorga de nuevo vacaciones que ya se tomaron.

Vive en su propio archivo a proposito. Cuando termine la migracion se le quita
el permiso licencias.cargaInicial al rol -- con eso la pestaña desaparece sin
redeploy -- y despues se borra este archivo y su linea en main.py, sin tener
que operar dentro de licenses.py.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.database import SessionLocal
from app.database.saldo_inicial_licencias import (
    ensure_table,
    saldos_de_empleado,
    upsert_saldos,
)
from app.routes.licenses import _le_aplica_al_empleado
from app.services.saldo_licencias import anios_de_carga

router = APIRouter(prefix="/licenses/carga-inicial", tags=["Carga inicial licencias"])

# Unica categoria que se arrastra de un anio a otro. El resto se consume
# dentro del anio, asi que cargarle anios viejos no tendria efecto.
CATEGORIA_ACUMULABLE = "Vacaciones"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SaldoCargado(BaseModel):
    anio: int
    categoria: str
    diasPendientes: int


class CargaInicialRequest(BaseModel):
    saldos: list[SaldoCargado]


def armar_catalogo_carga(
    categorias: list[str],
    saldos: dict[tuple[int, str], int],
    anio_actual: int,
    gender: str | None,
    role_name: str,
) -> dict:
    """
    Que se le ofrece cargar a este empleado, partido en dos bloques.

    diasPendientes viene en None cuando no se cargo nada y en 0 cuando se
    cargo un cero: son estados distintos y la pantalla los muestra distinto.

    El filtro de quien ve que categoria (_le_aplica_al_empleado) se reusa de
    app.routes.licenses en lugar de reimplementarse aca: es exactamente la
    misma regla que decide el saldo en balances, y duplicarla arriesgaria que
    las dos copias se desincronicen con el tiempo.
    """
    acumulables = []
    anuales = []

    for categoria in categorias:
        if not _le_aplica_al_empleado(categoria, gender, role_name):
            continue

        if categoria == CATEGORIA_ACUMULABLE:
            for anio in anios_de_carga(anio_actual):
                acumulables.append({
                    "anio": anio,
                    "categoria": categoria,
                    "diasPendientes": saldos.get((anio, categoria)),
                })
        else:
            anuales.append({
                "anio": anio_actual,
                "categoria": categoria,
                "diasPendientes": saldos.get((anio_actual, categoria)),
            })

    return {"acumulables": acumulables, "anuales": anuales}


@router.get("/{employee_id}")
def get_carga_inicial(
    employee_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("licencias.cargaInicial")),
):
    """Catalogo de lo que se le puede cargar, con lo ya cargado."""
    ensure_table(db)

    emp = db.execute(
        text("""
            SELECT e.gender, r.name AS roleName
            FROM Employee e
            INNER JOIN [User] u ON u.employeeId = e.id
            INNER JOIN Role r ON u.roleId = r.id
            WHERE e.id = :empId
        """),
        {"empId": employee_id},
    ).mappings().first()

    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    anio_actual = date.today().year

    categorias = [
        f["categoria"]
        for f in db.execute(
            text("""
                SELECT DISTINCT categoria
                FROM ConfiguracionLicencias
                ORDER BY categoria
            """)
        ).mappings().all()
    ]

    return armar_catalogo_carga(
        categorias=categorias,
        saldos=saldos_de_empleado(db, employee_id),
        anio_actual=anio_actual,
        gender=emp["gender"],
        role_name=(emp["roleName"] or "").lower(),
    )


@router.put("/{employee_id}")
def guardar_carga_inicial(
    employee_id: int,
    payload: CargaInicialRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("licencias.cargaInicial")),
):
    """
    Guarda una tanda de saldos.

    El id de quien carga sale del token y no del payload: esto mueve dias que
    se convierten en licencia paga, y la firma tiene que ser de quien
    efectivamente la hizo.
    """
    ensure_table(db)

    ventana = set(anios_de_carga(date.today().year))
    for s in payload.saldos:
        if s.diasPendientes < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Los dias de {s.categoria} {s.anio} no pueden ser negativos",
            )
        if s.anio not in ventana:
            raise HTTPException(
                status_code=400,
                detail=f"El anio {s.anio} esta fuera de la ventana de carga {sorted(ventana)}",
            )

    guardados = upsert_saldos(
        db,
        employee_id,
        [s.model_dump() for s in payload.saldos],
        cargado_por=user.get("employeeId"),
    )
    return {"guardados": guardados}
