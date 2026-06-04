from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN
import bcrypt
from datetime import datetime
router = APIRouter(prefix="/users", tags=["Users"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/register")
def register_user(data: dict, db: Session = Depends(get_db)):
    """
    Registra un nuevo usuario con rol por defecto 'User'
    Requiere: usuario, email, password
    """

    usuario = data.get("usuario")
    email = data.get("email")
    password = data.get("password")

    # Validaciones básicas
    if not usuario or not email or not password:
        raise HTTPException(status_code=400, detail="Campos obligatorios: usuario, email, password")

    # Verificar si el email ya está registrado
    query_user = text("SELECT * FROM [User] WHERE email = :email")
    existing_user = db.execute(query_user, {"email": email}).fetchone()
    if existing_user:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Verificar si el nombre de usuario ya existe
    query_username = text("SELECT * FROM [User] WHERE usuario = :usuario")
    existing_username = db.execute(query_username, {"usuario": usuario}).fetchone()
    if existing_username:
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    # Hashear la contraseña
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # Insertar usuario con rol por defecto "User"
    insert_query = text("""
        INSERT INTO [User] (usuario, email, password, roleId, updatedAt)
        VALUES (:usuario, :email, :password, :roleId,  GETDATE())
    """)

    try:
        db.execute(insert_query, {
            "usuario": usuario,
            "email": email,
            "password": hashed_password,
            "roleId": 2
        })
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar el usuario: {e}")

    return {"success": True, "message": "Usuario creado correctamente"}



# ===============================================
# GET: obtener todos los usuarios
# ===============================================
@router.get("/", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def get_all_users(db: Session = Depends(get_db)):
    query = text("""
        SELECT 
            u.id,
            u.usuario,
            u.activo,
            u.email,
            u.roleId,
            r.name AS role_name,
            e.id AS employee_id,
            e.name AS employee_name,
            e.dni,
            e.gender,
            e.email AS employee_email,
            d.id AS department_id,
            d.nombre AS department_name,
            o.id AS office_id,
            o.nombre AS office_name
        FROM [User] u
        LEFT JOIN Role r ON r.id = u.roleId
        LEFT JOIN Employee e ON e.id = u.employeeId
        LEFT JOIN Department d ON d.id = e.departmentId
        LEFT JOIN Office o ON o.id = e.officeId
    """)
    result = db.execute(query).fetchall()
    users = [dict(row._mapping) for row in result]
    return {"users": users}


@router.post("/employee", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def create_employee(request: Request, db: Session = Depends(get_db)):
    # Leer el JSON que llega del frontend
    body = await request.json()
    print("📩 Datos recibidos del frontend:", body)

    user_id = body.get("user_id")
    dni = body.get("dni")
    name = body.get("name")
    gender = body.get("gender")
    email = body.get("email")

    # Validar que estén todos los datos
    if not all([user_id, dni, name, gender, email]):
        raise HTTPException(status_code=400, detail="Faltan datos obligatorios")

    # Validar que el usuario exista
    user = db.execute(
        text("SELECT * FROM [User] WHERE id = :id"), {"id": user_id}
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Verificar constraint de DNI o Email en Employee
    duplicate_check = db.execute(
        text("SELECT id, dni, email FROM Employee WHERE dni = :dni OR email = :email"), 
        {"dni": dni, "email": email}
    ).fetchone()
    
    if duplicate_check:
        if duplicate_check.dni == dni:
            raise HTTPException(status_code=400, detail="El DNI ya se encuentra registrado por otro empleado.")
        if duplicate_check.email == email:
            raise HTTPException(status_code=400, detail="El Email ya se encuentra registrado por otro empleado.")

    try:
        # Crear empleado
        db.execute(
            text("""
                INSERT INTO Employee (dni, name, email, gender, updatedAt)
                VALUES (:dni, :name, :email, :gender, :updatedAt)
            """),
            {
                "dni": dni,
                "name": name,
                "email": email,
                "gender": gender,
                "updatedAt": datetime.now(),
            }
        )
        db.commit()

        # Obtener el ID del nuevo empleado
        employee_id = db.execute(
            text("SELECT id FROM Employee WHERE dni = :dni"), {"dni": dni}
        ).fetchone()[0]

        # Asociar empleado al usuario
        db.execute(
            text("""
                UPDATE [User]
                SET employeeId = :employee_id
                WHERE id = :user_id
            """),
            {"employee_id": employee_id, "user_id": user_id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno al guardar empleado: {str(e)}")

    return {"message": "Empleado creado y vinculado correctamente", "employee_id": employee_id}


@router.put("/employee", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def update_employee(request: Request, db: Session = Depends(get_db)):
    body = await request.json()

    employee_id = body.get("employee_id")
    dni = body.get("dni")
    name = body.get("name")
    gender = body.get("gender")
    email = body.get("email")

    # Validar que venga el ID
    if not employee_id:
        raise HTTPException(status_code=400, detail="Falta employee_id para actualizar")

    # Verificar que exista el empleado
    employee = db.execute(
        text("SELECT * FROM Employee WHERE id = :id"), {"id": employee_id}
    ).fetchone()
    if not employee:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Verificar constraint de DNI o Email en otros empleados
    duplicate_check = db.execute(
        text("SELECT id, dni, email FROM Employee WHERE (dni = :dni OR email = :email) AND id != :id"), 
        {"dni": dni, "email": email, "id": employee_id}
    ).fetchone()

    if duplicate_check:
        if duplicate_check.dni == dni:
            raise HTTPException(status_code=400, detail="El DNI ya se encuentra registrado por otro empleado.")
        if duplicate_check.email == email:
            raise HTTPException(status_code=400, detail="El Email ya se encuentra registrado por otro empleado.")

    try:
        # Actualizar datos
        db.execute(
            text("""
                UPDATE Employee
                SET dni = :dni, name = :name, gender = :gender, email = :email, updatedAt = :updatedAt
                WHERE id = :id
            """),
            {
                "dni": dni,
                "name": name,
                "gender": gender,
                "email": email,
                "updatedAt": datetime.now(),
                "id": employee_id,
            },
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno al actualizar empleado: {str(e)}")

    return {"message": "Empleado actualizado correctamente"}

# ===============================================
# PUT: actualizar el rol de un usuario
# ===============================================

@router.put("/{user_id}/role", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def update_user_role(user_id: str, request: Request, db: Session = Depends(get_db)):
    # Leer el JSON que llega del frontend
    body = await request.json()
    new_role_id = body.get("role")  # accedemos a la propiedad 'role' del JSON

    if not new_role_id:
        raise HTTPException(status_code=400, detail="El campo 'role' es obligatorio")

    # Verificar existencia del rol
    role_check = db.execute(text("SELECT * FROM Role WHERE id = :id"), {"id": new_role_id}).fetchone()
    if not role_check:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    # Actualizar el rol del usuario
    update_query = text("""
        UPDATE [User]
        SET roleId = :roleId
        WHERE id = :user_id
    """)
    db.execute(update_query, {"roleId": new_role_id, "user_id": user_id})
    db.commit()

    return {"message": "Rol actualizado correctamente", "user_id": user_id, "new_role_id": new_role_id}






@router.put("/{user_id}/activo", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def update_user_activo(user_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Cambia el estado 'activo' de un usuario.
    Se espera un JSON con {"activo": true} o {"activo": false}
    """
    body = await request.json()
    activo = body.get("activo")

    if activo is None:
        raise HTTPException(status_code=400, detail="El campo 'activo' es obligatorio")

    # Verificar que el usuario exista
    user = db.execute(text("SELECT * FROM [User] WHERE id = :id"), {"id": user_id}).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Actualizar estado
    db.execute(text("UPDATE [User] SET activo = :activo WHERE id = :user_id"),
               {"activo": activo, "user_id": user_id})
    db.commit()

    return {"message": "Estado actualizado correctamente", "user_id": user_id, "activo": activo}
