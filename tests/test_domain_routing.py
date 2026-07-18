"""正式域名访问时，客户前端与商家后台应自然分流。"""
from __future__ import annotations

from pathlib import Path

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


def test_chat_action_buttons_wrap_inside_the_assistant_bubble():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert ".acts button{" in html
    assert "max-width:100%;min-width:0;height:auto;min-height:44px" in html
    assert "font-size:12px;line-height:1.45;white-space:normal" in html
    assert "overflow-wrap:anywhere;word-break:break-word" in html


def test_mobile_login_uses_shrinkable_two_column_grid_without_inline_widths():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert 'class="login-email"' in html
    assert 'class="login-password"' in html
    assert 'style="width:190px"' not in html
    assert 'style="width:120px"' not in html
    assert ".login{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}" in html
    assert ".login .who{grid-column:1/-1;white-space:nowrap}" in html
    assert ".login input,.login button{width:100%;min-width:0}" in html
