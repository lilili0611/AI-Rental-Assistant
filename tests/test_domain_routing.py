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


def test_mobile_login_uses_shrinkable_layout_and_cat_head_profile_entry():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert 'class="login-email auth-input"' in html
    assert 'class="login-password auth-input"' in html
    assert 'style="width:190px"' not in html
    assert 'style="width:120px"' not in html
    assert ".login{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}" in html
    assert ".login .who{grid-column:1/-1;white-space:nowrap}" in html
    assert ".login input,.login button{width:100%;min-width:0}" in html
    assert ".hbar.user-on{flex-wrap:nowrap;align-items:center}" in html
    assert 'class="user-entry"' in html
    assert 'onclick="openProfile()"' in html
    assert 'class="user-cat-frame"' in html
    assert 'class="user-entry-label">我的</span>' in html
    assert 'id="headerAvatar"' not in html
    assert 'id="headerUserName"' not in html
    assert ".login.signed-in .user-entry{width:64px;min-width:64px;height:56px;min-height:56px" in html


def test_mobile_ai_panel_voice_fallback_and_profile_center_are_present():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert 'id="mobileAiDock"' in html
    assert "问 AI 或按住说话" in html
    assert 'id="aiPanel"' in html
    assert 'id="aiMsgs"' in html
    assert "['msgs','aiMsgs']" in html
    assert "window.SpeechRecognition||window.webkitSpeechRecognition" in html
    assert "rec.lang='zh-CN'" in html
    assert "当前浏览器不支持语音识别，请使用键盘输入" in html
    assert "本站不保存音频" in html
    assert "env(safe-area-inset-bottom)" in html
    assert 'id="profilePanel"' in html
    assert 'id="profileAvatar"' in html
    assert 'id="myOrders"' in html
    assert "'/api/auth/change-password'" in html
    assert "'/api/auth/me'" in html


def test_mobile_ai_panel_prevents_keyboard_zoom_and_tracks_visual_viewport():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert "input,select,textarea{font-size:16px}" in html
    assert "window.visualViewport" in html
    assert "--app-height" in html
    assert "--app-top" in html
    assert "height:var(--app-height,100dvh)" in html
    assert "max-width:100vw" in html
    assert "if(input&&window.matchMedia('(max-width:900px)').matches)input.blur()" in html
    assert "restoreMobileViewport(input);addBub('u',txt)" in html
    assert "html,body{margin:0;max-width:100%;overflow-x:hidden}" in html
    assert "overflow-wrap:anywhere;word-break:break-word" in html
    assert "maximum-scale" not in html
    assert "user-scalable=no" not in html


def test_checkout_collects_and_displays_shipping_address_responsively():
    customer = Path("app/static/index.html").read_text(encoding="utf-8")
    admin = Path("app/static/admin.html").read_text(encoding="utf-8")

    for label in ("收货人姓名", "手机号码", "省", "市", "区/县", "详细地址"):
        assert label in customer
    assert "shipping_address:shippingAddress" in customer
    assert "collectShippingAddress()" in customer
    assert "确认地址并立即下单" in customer
    assert ".shipping-grid{grid-template-columns:1fr}" in customer
    assert "o.shipping_address.full_address" in customer
    assert "const shipping=p.shipping_address||{};SHIPPING_DRAFT={}" in customer
    assert "设备、租期和收货信息已带入" in customer
    assert "设备和租期已带入，请在下单页补全收货信息" in customer

    assert "<th>收货信息</th>" in admin
    assert "o.shipping_address.full_address" in admin
    assert 'colspan="8"' in admin
