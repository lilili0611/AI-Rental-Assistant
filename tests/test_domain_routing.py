"""正式域名访问时，客户前端与商家后台应自然分流。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_customer_domain_serves_customer_frontend():
    response = client.get("/", headers={"host": "bozipaopao.cn"})

    assert response.status_code == 200
    assert "猫猫头相机租赁 · 租客自助下单" in response.text


def test_admin_domain_root_serves_admin_frontend():
    response = client.get("/", headers={"host": "admin.bozipaopao.cn"})

    assert response.status_code == 200
    assert "猫猫头相机租赁 · 商家后台" in response.text


def test_customer_domain_admin_path_redirects_to_admin_domain():
    response = client.get(
        "/admin",
        headers={"host": "bozipaopao.cn"},
        follow_redirects=False,
    )

    assert response.status_code in {301, 302, 307, 308}
    assert response.headers["location"] == "https://admin.bozipaopao.cn/"


def test_local_admin_path_still_serves_admin_frontend():
    response = client.get("/admin", headers={"host": "127.0.0.1:8000"})

    assert response.status_code == 200
    assert "猫猫头相机租赁 · 商家后台" in response.text
