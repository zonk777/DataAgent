from types import SimpleNamespace

import pytest

from app.models import MySQLImportRequest, MySQLSchemaRequest
from app.services.datasets import _mysql_pool_key, _mysql_ssl_config, _ssh_tunnel


def test_mysql_request_models_accept_ssl_and_ssh_fields() -> None:
    schema = MySQLSchemaRequest(
        host="10.0.0.10",
        username="readonly",
        ssl_enabled=True,
        ssl_ca="C:/certs/ca.pem",
        ssh_enabled=True,
        ssh_host="bastion.example.com",
        ssh_username="ubuntu",
        ssh_password="secret",
    )
    assert schema.ssh_port == 22
    assert schema.ssh_host == "bastion.example.com"

    payload = MySQLImportRequest(
        host="10.0.0.10",
        username="readonly",
        database="demo",
        table="orders",
        ssh_enabled=True,
        ssh_host="bastion.example.com",
        ssh_username="ubuntu",
        ssh_pkey="C:/Users/me/.ssh/id_rsa",
    )
    assert payload.database == "demo"
    assert payload.ssh_pkey.endswith("id_rsa")


def test_mysql_pool_key_isolated_by_ssl_and_ssh_options() -> None:
    base = SimpleNamespace(
        host="127.0.0.1",
        port=3306,
        username="root",
        password="",
        ssl_enabled=False,
        ssl_ca=None,
        ssl_cert=None,
        ssl_key=None,
        ssh_enabled=False,
        ssh_host=None,
        ssh_port=22,
        ssh_username=None,
        ssh_password=None,
        ssh_pkey=None,
        ssh_private_key_passphrase=None,
    )
    via_ssh = SimpleNamespace(**{**base.__dict__, "ssh_enabled": True, "ssh_host": "bastion", "ssh_username": "ubuntu", "ssh_password": "secret"})
    via_ssl = SimpleNamespace(**{**base.__dict__, "ssl_enabled": True, "ssl_ca": "ca.pem"})

    assert _mysql_pool_key(base, "demo") != _mysql_pool_key(via_ssh, "demo")
    assert _mysql_pool_key(base, "demo") != _mysql_pool_key(via_ssl, "demo")


def test_mysql_ssl_config_uses_optional_certificate_paths() -> None:
    payload = SimpleNamespace(ssl_enabled=True, ssl_ca="ca.pem", ssl_cert="client.pem", ssl_key="client.key")

    assert _mysql_ssl_config(payload) == {
        "ca": "ca.pem",
        "cert": "client.pem",
        "key": "client.key",
    }


def test_ssh_tunnel_requires_host_user_and_authentication() -> None:
    missing_host = SimpleNamespace(ssh_enabled=True, ssh_host="", ssh_username="ubuntu", ssh_password="secret", ssh_pkey=None)
    with pytest.raises(ValueError, match="SSH 主机"):
        _ssh_tunnel(missing_host)

    missing_auth = SimpleNamespace(ssh_enabled=True, ssh_host="bastion", ssh_username="ubuntu", ssh_password="", ssh_pkey="")
    with pytest.raises(ValueError, match="SSH 密码或私钥"):
        _ssh_tunnel(missing_auth)
