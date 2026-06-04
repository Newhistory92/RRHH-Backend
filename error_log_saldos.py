Traceback (most recent call last):
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
    ~~~~~~~~~~~~~~~~~~~~~~~^
        cursor, str_statement, effective_parameters, context
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\default.py", line 951, in do_execute
    cursor.execute(statement, parameters)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
pyodbc.ProgrammingError: ('42S22', "[42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]El nombre de columna 'tipoContrato' no es válido. (207) (SQLExecDirectW); [42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]No se puede preparar la instrucción o instrucciones. (8180)")

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "C:\Users\Emiliano\Documents\Backend_RRHH\app\routes\licenses.py", line 263, in get_license_saldos
    seed_default_configs(db, current_cycle, tipo_contrato)
    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\app\routes\licenses.py", line 236, in seed_default_configs
    exists = db.execute(text("SELECT id FROM ConfiguracionLicencias WHERE anio = :anio AND tipo = :tipo AND tipoContrato = :contrato"),
             ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                        {"anio": anio, "tipo": c["tipo"], "contrato": contrato}).first()
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\orm\session.py", line 2351, in execute
    return self._execute_internal(
           ~~~~~~~~~~~~~~~~~~~~~~^
        statement,
        ^^^^^^^^^^
    ...<4 lines>...
        _add_event=_add_event,
        ^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\orm\session.py", line 2258, in _execute_internal
    result = conn.execute(
        statement, params or {}, execution_options=execution_options
    )
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1419, in execute
    return meth(
        self,
        distilled_parameters,
        execution_options or NO_OPTIONS,
    )
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\sql\elements.py", line 526, in _execute_on_connection
    return connection._execute_clauseelement(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        self, distilled_params, execution_options
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1641, in _execute_clauseelement
    ret = self._execute_context(
        dialect,
    ...<8 lines>...
        cache_hit=cache_hit,
    )
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1846, in _execute_context
    return self._exec_single_context(
           ~~~~~~~~~~~~~~~~~~~~~~~~~^
        dialect, context, statement, parameters
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1986, in _exec_single_context
    self._handle_dbapi_exception(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        e, str_statement, effective_parameters, cursor, context
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 2355, in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
    ~~~~~~~~~~~~~~~~~~~~~~~^
        cursor, str_statement, effective_parameters, context
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\Emiliano\Documents\Backend_RRHH\venv\Lib\site-packages\sqlalchemy\engine\default.py", line 951, in do_execute
    cursor.execute(statement, parameters)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
sqlalchemy.exc.ProgrammingError: (pyodbc.ProgrammingError) ('42S22', "[42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]El nombre de columna 'tipoContrato' no es válido. (207) (SQLExecDirectW); [42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]No se puede preparar la instrucción o instrucciones. (8180)")
[SQL: SELECT id FROM ConfiguracionLicencias WHERE anio = ? AND tipo = ? AND tipoContrato = ?]
[parameters: (2025, 'LAR', 'permanente')]
(Background on this error at: https://sqlalche.me/e/20/f405)
