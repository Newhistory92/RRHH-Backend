"""
Cliente HTTP hacia el endpoint de metricas de Turnero.

El parseo se testea puro, sin red: se le pasa el payload tal como lo devuelve
el endpoint y se verifica que se traduzca a los dataclasses propios. La llamada
HTTP en si no se testea aca -seria testear requests-, pero si se verifica que
un Turnero caido no rompa a RRHH.
"""

from app.services.turnero_client import MetricaTurnero, parsear_metricas

PAYLOAD = {
    "empleados": [
        {
            "dniInstitucional": "30111222",
            "empleadoNombre": "Ana Perez",
            "atendidos": 120,
            "validas": 100,
            "breves": 15,
            "anomalias": 5,
            "promedioSegundos": 480.0,
            "desvioContraMedianaSegundos": -30.0,
            "horasBox": 140.5,
        }
    ]
}


def test_indexa_por_dni():
    """El DNI es la clave de vinculo con Employee, no el id interno."""
    r = parsear_metricas(PAYLOAD)
    assert set(r.keys()) == {"30111222"}
    assert isinstance(r["30111222"], MetricaTurnero)


def test_traduce_los_campos():
    m = parsear_metricas(PAYLOAD)["30111222"]
    assert m.atendidos == 120
    assert m.validas == 100
    assert m.anomalias == 5
    assert m.horasBox == 140.5
    assert m.desvioContraMedianaSegundos == -30.0


def test_tolera_promedios_nulos():
    """Un empleado sin atenciones con tiempo devuelve null en los promedios."""
    payload = {"empleados": [{
        "dniInstitucional": "30111222", "empleadoNombre": "Ana",
        "atendidos": 0, "validas": 0, "breves": 0, "anomalias": 0,
        "promedioSegundos": None, "desvioContraMedianaSegundos": None,
        "horasBox": 0,
    }]}
    m = parsear_metricas(payload)["30111222"]
    assert m.promedioSegundos is None
    assert m.desvioContraMedianaSegundos is None


def test_un_payload_vacio_no_rompe():
    assert parsear_metricas({"empleados": []}) == {}
    assert parsear_metricas({}) == {}


def test_descarta_filas_sin_dni():
    """Sin DNI no hay con que vincular: la fila no sirve y se ignora."""
    payload = {"empleados": [
        {"dniInstitucional": None, "atendidos": 5, "validas": 5, "breves": 0,
         "anomalias": 0, "promedioSegundos": None,
         "desvioContraMedianaSegundos": None, "horasBox": 1},
    ]}
    assert parsear_metricas(payload) == {}
