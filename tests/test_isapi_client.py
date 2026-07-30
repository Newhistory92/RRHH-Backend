import pytest
from app.services import isapi_client as c


def test_allowlist_tiene_exactamente_tres_endpoints():
    assert len(c.ALLOWLIST) == 3
    assert ("GET", c.ENDPOINT_DEVICE_INFO) in c.ALLOWLIST
    assert ("POST", c.ENDPOINT_ACS_EVENT) in c.ALLOWLIST
    assert ("POST", c.ENDPOINT_USER_SEARCH) in c.ALLOWLIST


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "PATCH"])
def test_rechaza_verbos_de_escritura(metodo):
    with pytest.raises(c.ISAPINotAllowed):
        c.pedir(metodo, "10.25.2.24", c.ENDPOINT_DEVICE_INFO)


@pytest.mark.parametrize("path", [
    "/ISAPI/AccessControl/UserInfo/Delete",
    "/ISAPI/AccessControl/UserInfo/Record",
    "/ISAPI/AccessControl/UserInfo/Modify",
    "/ISAPI/AccessControl/RemoteControl/door/1",
    "/ISAPI/System/time",
])
def test_rechaza_endpoints_que_escriben(path):
    with pytest.raises(c.ISAPINotAllowed):
        c.pedir("POST", "10.25.2.24", path, {"algo": 1})


def test_relojes_configurados_parsea_lista(monkeypatch):
    monkeypatch.setenv("RELOJ_IPS", " 10.25.2.24 , 10.25.2.25 ,")
    assert c.relojes_configurados() == ["10.25.2.24", "10.25.2.25"]
