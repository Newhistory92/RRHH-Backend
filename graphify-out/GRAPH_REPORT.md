# Graph Report - .  (2026-06-19)

## Corpus Check
- Corpus is ~18,906 words - fits in a single context window. You may not need a graph.

## Summary
- 207 nodes · 298 edges · 20 communities
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]

## God Nodes (most connected - your core abstractions)
1. `Session` - 15 edges
2. `require_roles()` - 10 edges
3. `Session` - 9 edges
4. `get_current_user()` - 6 edges
5. `Session` - 6 edges
6. `Session` - 6 edges
7. `_in_cooldown()` - 6 edges
8. `Session` - 6 edges
9. `Session` - 6 edges
10. `toggle_table_active()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `pyodbc.ProgrammingError: Invalid parameter type (param-index=1 param-type=dict, HY105)` --semantically_similar_to--> `pyodbc.ProgrammingError: Invalid column name 'tipoContrato' (42S22)`  [INFERRED] [semantically similar]
  error_log.txt → error_log_saldos.txt
- `update_license_status (app/routes/licenses.py:818)` --conceptually_related_to--> `get_license_saldos (app/routes/licenses.py:263)`  [INFERRED]
  error_log.txt → error_log_saldos.txt
- `test()` --calls--> `get_global_stats()`  [EXTRACTED]
  test_global_stats.py → app/routes/stats.py
- `seed_default_configs (app/routes/licenses.py:236)` --calls--> `SQLAlchemy (ORM/engine library)`  [EXTRACTED]
  error_log_saldos.txt → error_log.txt
- `pyodbc.ProgrammingError: Invalid column name 'tipoContrato' (42S22)` --references--> `pyodbc (ODBC DB driver)`  [EXTRACTED]
  error_log_saldos.txt → error_log.txt

## Import Cycles
- None detected.

## Communities (20 total, 0 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.12
Nodes (27): Session, calcular_dias_vacaciones(), create_configuracion(), create_license_request(), delete_configuracion(), get_configuraciones(), get_dynamic_license_balance(), get_employee_supervisor() (+19 more)

### Community 1 - "Community 1"
Cohesion: 0.15
Nodes (17): Session, create_permission(), decimal_to_minutes(), get_all_employees(), get_org_analysis_data(), _group_by(), _null_entry(), Router /rrhh — Vista principal de empleados para el módulo RRHH.  OPTIMIZACIÓN N (+9 more)

### Community 2 - "Community 2"
Cohesion: 0.15
Nodes (12): Middleware de autorización para FastAPI.  Provee dos dependencias reutilizables:, Retorna una dependencia FastAPI que verifica que el usuario autenticado     teng, require_roles(), Session, Session, delete_academic_record(), get_employee_details(), Elimina un registro académico (AcademicRecord) por su ID. (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.18
Nodes (16): Request, Session, BaseModel, assign_employee_to_department(), assign_employee_to_office(), create_department(), create_office(), delete_department() (+8 more)

### Community 4 - "Community 4"
Cohesion: 0.17
Nodes (16): Session, check_cooldown(), get_available_skills(), get_test_history(), get_test_questions(), _in_cooldown(), _pct_to_score(), Router /tests — Módulo de tests técnicos para empleados.  Endpoints:   GET  /tes (+8 more)

### Community 5 - "Community 5"
Cohesion: 0.16
Nodes (12): setup_cors(), startup(), Request, Session, OAuth2PasswordRequestForm, get_me(), init_blacklist(), login() (+4 more)

### Community 6 - "Community 6"
Cohesion: 0.16
Nodes (13): get_current_user(), Session, Dependencia FastAPI que:       1. Extrae el token Bearer del header Authorizatio, Session, get_evaluable_peers(), get_feedback_status(), get_received_feedback(), Router /feedback — Evaluación entre pares (Feedback 360°).  Endpoints:   GET  /f (+5 more)

### Community 7 - "Community 7"
Cohesion: 0.18
Nodes (13): Session, delete_soft_skill(), delete_technical_test(), get_soft_skills(), get_technical_config(), Saves (creates or updates) a technical test (TechnicalSkill) and its questions/a, Returns the professions and testsByProfession structure as expected by the front, Soft-deletes a technical test by setting activo = 0. (+5 more)

### Community 8 - "Community 8"
Cohesion: 0.30
Nodes (8): Session, calculate_productivity_scores(), fetch_all_employees_data(), get_dashboard(), get_global_stats(), get_metadata(), sync_productivity_scores(), test()

### Community 9 - "Community 9"
Cohesion: 0.29
Nodes (10): Request, Session, create_employee(), get_all_users(), Registra un nuevo usuario con rol por defecto 'User'     Requiere: usuario, ema, Cambia el estado 'activo' de un usuario.     Se espera un JSON con {"activo": t, register_user(), update_employee() (+2 more)

### Community 10 - "Community 10"
Cohesion: 0.29
Nodes (9): pyodbc (ODBC DB driver), SQLAlchemy (ORM/engine library), Aprobaciones (SQL table), pyodbc.ProgrammingError: Invalid parameter type (param-index=1 param-type=dict, HY105), ConfiguracionLicencias (SQL table), pyodbc.ProgrammingError: Invalid column name 'tipoContrato' (42S22), get_license_saldos (app/routes/licenses.py:263), seed_default_configs (app/routes/licenses.py:236) (+1 more)

### Community 11 - "Community 11"
Cohesion: 0.39
Nodes (6): Request, Session, get_config(), get_tables_status(), save_config(), toggle_table_active()

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (3): Session, get_usuarios_acceso(), Obtiene todos los usuarios de [ObraSocial].[dbo].[UsuarioAcceso]     Esta base d

## Knowledge Gaps
- **4 isolated node(s):** `Session`, `Request`, `OAuth2PasswordRequestForm`, `Session`
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `require_roles()` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Why does `get_current_user()` connect `Community 6` to `Community 0`, `Community 2`, `Community 4`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **What connects `Session`, `Middleware de autorización para FastAPI.  Provee dos dependencias reutilizables:`, `Dependencia FastAPI que:       1. Extrae el token Bearer del header Authorizatio` to the rest of the system?**
  _51 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.11576354679802955 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.14619883040935672 - nodes in this community are weakly interconnected._