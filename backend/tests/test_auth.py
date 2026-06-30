from app.db import connect, initialize_database
from app.services.auth import authenticate, create_admin, hash_password, verify_password


def test_password_hash_verification() -> None:
    password_hash = hash_password("18437431")
    assert verify_password("18437431", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False
    assert "18437431" not in password_hash


def test_initial_admin_is_seeded(monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_DATABASE", "dataagent_test")
    initialize_database()

    admin = authenticate("liuze", "18437431")
    assert admin is not None
    assert admin["username"] == "liuze"
    assert admin["is_initial_admin"] is True


def test_initial_admin_can_create_normal_admin(monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_DATABASE", "dataagent_test")
    initialize_database()
    initial = authenticate("liuze", "18437431")
    created = create_admin("normal_admin", "123456", initial["id"])

    assert created["username"] == "normal_admin"
    assert created["is_initial_admin"] is False
    with connect() as conn:
        row = conn.execute("SELECT password_hash FROM admin_users WHERE username = %s", ("normal_admin",)).fetchone()
    assert row is not None
    assert verify_password("123456", row["password_hash"]) is True
