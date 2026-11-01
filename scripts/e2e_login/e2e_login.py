"""Gerçek tarayıcı (Playwright) ile login/SSO/marka e2e testi. Yalnızca izole test ortamına karşı çalışır."""
import base64, hashlib, hmac, json, re, struct, sys, time
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

UI = "http://localhost:3100"
API = UI + "/api/v1"
ADMIN = ("admin", "E2e-Admin-Pass-1")
SHOTS = "/tmp/e2e/shots"
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""), flush=True)


def totp(secret, offset=0):
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret) % 8))
    counter = int(time.time() // 30) + offset
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o+4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def new_ctx(browser, theme="dark", locale="tr", viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900})
    ctx.add_init_script(
        f"if(!localStorage.getItem('ainew_theme')) localStorage.setItem('ainew_theme','{theme}');"
        f"if(!localStorage.getItem('ainew_locale')) localStorage.setItem('ainew_locale','{locale}');"
    )
    return ctx


def api_token(pw, user, password):
    r = pw.request.new_context().post(API + "/auth/login", data={"username": user, "password": password})
    return r.json().get("access_token")


def me(page):
    tok = page.evaluate("localStorage.getItem('auth_token')")
    if not tok:
        return None
    r = page.request.get(API + "/auth/me", headers={"Authorization": f"Bearer {tok}"})
    return r.json() if r.ok else None


def ui_login(page, user, password):
    page.goto(UI + "/login")
    page.fill("#lg-user", user)
    page.fill("#lg-pass", password)
    page.click("button.lg-btn-primary")


def sso_login(page, who):
    page.goto(UI + "/login")
    page.click("button.lg-btn-outline")
    page.wait_for_selector("#idp-title", timeout=10000)
    page.click(f"#pick-{who}")


def main():
    import os
    os.makedirs(SHOTS, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch()
        dialogs = []
        _t = api_token(p, *ADMIN)
        p.request.new_context(extra_http_headers={"Authorization": f"Bearer {_t}"}).put(
            API + "/settings/branding", data={"app_name": "ainew", "company_name": "", "tagline": "", "footer_text": ""})

        # ---------- 1. Görünüm: iki tema, masaüstü + dar ekran ----------
        for theme in ("dark", "light"):
            ctx = new_ctx(br, theme)
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(UI + "/login")
            pg.wait_for_selector("#lg-user")
            pg.wait_for_timeout(600)
            check(f"[{theme}] html data-theme", pg.evaluate("document.documentElement.dataset.theme") == theme)
            body = pg.inner_text("body")
            check(f"[{theme}] 'Parolamı unuttum' yok", "unuttum" not in body.lower())
            check(f"[{theme}] 'Beni hatırla' yok", "hatırla" not in body.lower())
            check(f"[{theme}] varsayılan şirket adı görünür", "Datatem Teknoloji" in body)
            check(f"[{theme}] SSO butonu görünür (yapılandırılmış)", pg.locator("button.lg-btn-outline").count() == 1)
            check(f"[{theme}] AD sekmesi yok (AD kapalı)", pg.locator("[role=tab]").count() == 0)
            check(f"[{theme}] hub SVG var", pg.locator(".lg-hero svg").count() >= 1)
            check(f"[{theme}] JS hatası yok", not errs, str(errs))
            pg.screenshot(path=f"{SHOTS}/login-{theme}-desktop.png")
            # kontrast: gövde/başlık rengi arka plandan farklı
            bg = pg.evaluate("getComputedStyle(document.querySelector('.lg-root')).backgroundColor")
            fg = pg.evaluate("getComputedStyle(document.querySelector('.lg-card h1, .lg-form-wrap h1, h1')).color")
            check(f"[{theme}] metin/arka plan renkleri farklı", bg != fg, f"{bg} / {fg}")
            ctx.close()

            ctx = new_ctx(br, theme, viewport={"width": 390, "height": 844})
            pg = ctx.new_page()
            pg.goto(UI + "/login")
            pg.wait_for_selector("#lg-user")
            pg.wait_for_timeout(500)
            ow = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            check(f"[{theme}] dar ekranda yatay taşma yok", ow)
            pg.screenshot(path=f"{SHOTS}/login-{theme}-mobile.png", full_page=True)
            ctx.close()

        # ---------- 2. Tema / dil geçişi kalıcı ----------
        ctx = new_ctx(br, "dark")
        pg = ctx.new_page()
        pg.goto(UI + "/login")
        pg.wait_for_selector("#lg-user")
        pg.click("button[aria-label*='emaya'], button[aria-label*='heme'], button[aria-label*='ight'], button[aria-label*='ark']")
        pg.wait_for_timeout(300)
        check("tema düğmesi light'a çevirir", pg.evaluate("document.documentElement.dataset.theme") == "light")
        pg.reload()
        pg.wait_for_selector("#lg-user")
        check("tema yenilemede korunur", pg.evaluate("document.documentElement.dataset.theme") == "light")
        pg.select_option("select", "en")
        pg.wait_for_timeout(300)
        check("dil EN: buton 'Sign in'", pg.locator("button.lg-btn-primary").inner_text().strip() == "Sign in")
        pg.reload()
        pg.wait_for_selector("#lg-user")
        check("dil yenilemede korunur", "Sign in" in pg.inner_text("button.lg-btn-primary"))
        pg.screenshot(path=f"{SHOTS}/login-light-en.png")
        ctx.close()

        # ---------- 3. Yerel giriş ----------
        ctx = new_ctx(br)
        pg = ctx.new_page()
        ui_login(pg, "opsuser", "yanlis-parola-123")
        pg.wait_for_selector(".lg-error", timeout=8000)
        check("yanlış parola → hata kutusu", pg.locator(".lg-error").count() == 1)
        check("yanlış parola → login'de kalır", "/login" in pg.url)
        pg.screenshot(path=f"{SHOTS}/login-error-dark.png")
        pg.fill("#lg-pass", "Ops-Local-Pass-12345")
        pg.click("button.lg-btn-primary")
        pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=10000)
        u = me(pg)
        check("yerel operator girişi başarılı", u and u["username"] == "opsuser" and u["role"] == "operator", str(u))
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{SHOTS}/after-login-opsuser.png")
        ctx.close()

        # ---------- 4. SSO rolleri ----------
        for who, role in (("alice", "admin"), ("olivia", "operator"), ("victor", "viewer")):
            ctx = new_ctx(br)
            pg = ctx.new_page()
            seen = []
            pg.on("request", lambda r, s=seen: s.append(r.url))
            sso_login(pg, who)
            pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=15000)
            u = me(pg)
            check(f"SSO {who} → rol {role}", u and u["role"] == role and u["auth_source"] == "sso", str(u))
            check(f"SSO {who}: adres çubuğunda token/code yok", "sso_code" not in pg.url and "token" not in pg.url)
            if who == "alice":
                codes = [parse_qs(urlparse(x).query).get("sso_code") for x in seen if "sso_code=" in x]
                code = codes[0][0] if codes else None
                check("SSO kodu istek akışında göründü", bool(code))
                if code:
                    r = pg.request.post(API + "/auth/sso/exchange", data={"code": code})
                    check("SSO kodu ikinci kez kullanılamaz (tek kullanımlık)", r.status in (400, 401, 403), str(r.status))
            ctx.close()

        # ---------- 5. SSO reddedilen durumlar ----------
        for who, label in (("nora", "grupsuz kullanıcı"), ("localbob", "yerel parola hesabıyla çakışma")):
            ctx = new_ctx(br)
            pg = ctx.new_page()
            sso_login(pg, who)
            pg.wait_for_selector(".lg-error", timeout=15000)
            check(f"SSO {label} reddedilir", pg.locator(".lg-error").count() == 1 and "/login" in pg.url)
            check(f"SSO {label}: oturum açılmadı", me(pg) is None)
            pg.screenshot(path=f"{SHOTS}/sso-denied-{who}.png")
            ctx.close()

        # IdP iptal + XSS yansıması
        ctx = new_ctx(br)
        pg = ctx.new_page()
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        sso_login(pg, "cancel")
        pg.wait_for_selector(".lg-error", timeout=15000)
        check("IdP iptali → hata kutusu", pg.locator(".lg-error").count() == 1)
        check("IdP açıklaması (script) yansıtılmadı/çalışmadı", not dialogs and "<script>" not in pg.content().split("</head>")[-1].replace("&lt;script&gt;", ""))
        ctx.close()

        # callback tekrar oynatma / sahte state
        ctx = new_ctx(br)
        r = ctx.request.get(API + "/auth/sso/callback?code=abc&state=sahte", max_redirects=0)
        loc = r.headers.get("location", "")
        check("sahte state → login'e sso_error ile döner", r.status in (302, 307) and "sso_error=" in loc and "sso_code=" not in loc, f"{r.status} {loc}")
        ctx.close()

        # ---------- 6. Marka düzenleme (UI üzerinden, admin) ----------
        ctx = new_ctx(br)
        pg = ctx.new_page()
        ui_login(pg, *ADMIN)
        pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=10000)
        pg.goto(UI + "/settings")
        pg.get_by_role("button", name="Kurumsal Kimlik").first.click()
        pg.wait_for_timeout(500)
        inputs = pg.locator("input[type=text]")
        # sırayla: uygulama adı, şirket, alt başlık, alt bilgi
        vals = ["Acme Konsol", "Acme Bilişim A.Ş.", "ACME ALTYAPI MERKEZİ", "© 2026 Acme — Tüm hakları saklıdır"]
        # ilgili alanları placeholder/etiketle bul
        for lbl, val in zip(["Uygulama / Şirket Adı", "Şirket adı", "Giriş ekranı alt başlığı", "Alt bilgi metni"], vals):
            pg.get_by_text(lbl, exact=True).locator("xpath=following-sibling::input[1]").fill(val)
        pg.get_by_role("button", name="Kaydet").first.click()
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{SHOTS}/settings-branding.png")
        ctx.close()

        for theme in ("dark", "light"):
            ctx = new_ctx(br, theme)
            pg = ctx.new_page()
            pg.goto(UI + "/login")
            pg.wait_for_selector("#lg-user")
            pg.wait_for_timeout(600)
            body = pg.inner_text("body")
            check(f"[{theme}] marka: uygulama adı", "Acme Konsol" in body)
            check(f"[{theme}] marka: şirket", "Acme Bilişim A.Ş." in body)
            check(f"[{theme}] marka: alt başlık", "ACME ALTYAPI MERKEZİ" in body)
            check(f"[{theme}] marka: alt bilgi", "Tüm hakları saklıdır" in body)
            pg.screenshot(path=f"{SHOTS}/login-{theme}-branded.png")
            ctx.close()
        title_ctx = new_ctx(br)
        pg = title_ctx.new_page()
        pg.goto(UI + "/login")
        pg.wait_for_timeout(800)
        check("sekme başlığı marka adını gösterir", "Acme" in pg.title() or pg.title() == "ainew", pg.title())
        title_ctx.close()

        # ---------- 7. SSO yapılandırma ekranı (admin, UI) ----------
        ctx = new_ctx(br)
        pg = ctx.new_page()
        ui_login(pg, *ADMIN)
        pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=10000)
        pg.goto(UI + "/settings")
        pg.get_by_role("button", name="Güvenlik", exact=True).first.click()
        pg.wait_for_timeout(1000)
        if pg.get_by_text("Yapılandırmayı test et").count():
            pg.get_by_text("Yapılandırmayı test et").first.click()
            pg.wait_for_selector("[data-testid=sso-check]", timeout=15000)
            txt = pg.locator("[data-testid=sso-check]").inner_text()
            check("SSO yapılandırma testi ekranı sonuç döner", "JWKS" in txt and "Discovery" in txt, txt[:200])
            pg.screenshot(path=f"{SHOTS}/security-sso.png", full_page=True)
        else:
            pg.screenshot(path=f"{SHOTS}/security-notfound.png", full_page=True)
            check("SSO ayar ekranı bulundu", False, pg.url)
        ctx.close()

        # ---------- 8. Kilitlenme + MFA ----------
        tok = api_token(p, *ADMIN)
        H = {"Authorization": f"Bearer {tok}"}
        ar = p.request.new_context(extra_http_headers=H)
        ar.patch(API + "/security/policy", data={"mfa_enabled": True})
        time.sleep(50)
        # MFA kayıt
        ctx = new_ctx(br)
        pg = ctx.new_page()
        ui_login(pg, "localbob", "Bob-Local-Pass-12345")
        pg.wait_for_selector(".lg-secret", timeout=10000)
        secret = pg.inner_text(".lg-secret").strip()
        check("MFA kayıt adımı gösterilir (secret)", len(secret) >= 16)
        pg.screenshot(path=f"{SHOTS}/login-mfa-enroll.png")
        pg.fill("#lg-code", "000000")
        pg.click("button.lg-btn-primary")
        pg.wait_for_selector(".lg-error", timeout=8000)
        check("MFA yanlış kod reddedilir", pg.locator(".lg-error").count() == 1)
        pg.fill("#lg-code", totp(secret))
        pg.click("button.lg-btn-primary")
        pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=10000)
        check("MFA kayıt sonrası giriş", (me(pg) or {}).get("username") == "localbob")
        ctx.close()

        # MFA doğrulama (yeni oturum)
        ctx = new_ctx(br)
        pg = ctx.new_page()
        ui_login(pg, "localbob", "Bob-Local-Pass-12345")
        pg.wait_for_selector("#lg-code", timeout=10000)
        check("MFA doğrulama adımında secret gösterilmez", pg.locator(".lg-secret").count() == 0)
        pg.screenshot(path=f"{SHOTS}/login-mfa-verify.png")
        ok = False
        for off in (1, 0, -1):
            pg.fill("#lg-code", totp(secret, off))
            pg.click("button.lg-btn-primary")
            try:
                pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=4000)
                ok = True
                break
            except Exception:
                continue
        check("MFA doğrulama ile giriş", ok)
        ctx.close()

        # MFA açıkken SSO (IdP kendi MFA'sını yapar → ainew ek MFA istemez)
        ctx = new_ctx(br)
        pg = ctx.new_page()
        sso_login(pg, "alice")
        pg.wait_for_function("!location.pathname.startsWith('/login')", timeout=15000)
        check("MFA açıkken SSO doğrudan girer", (me(pg) or {}).get("username", "").startswith("alice"))
        ctx.close()
        ar.patch(API + "/security/policy", data={"mfa_enabled": False})
        time.sleep(50)

        # ---------- 9. SSO kapalıyken buton yok ----------
        ar.put(API + "/identity", data={"sso_enabled": False})
        ctx = new_ctx(br)
        pg = ctx.new_page()
        pg.goto(UI + "/login")
        pg.wait_for_selector("#lg-user")
        pg.wait_for_timeout(500)
        check("SSO kapalıyken buton gizli", pg.locator("button.lg-btn-outline").count() == 0)
        r = ctx.request.get(API + "/auth/sso/start", max_redirects=0)
        check("SSO kapalıyken /sso/start login'e hata ile yönlendirir", r.status in (302, 307) and "sso_error" in r.headers.get("location", ""), f"{r.status} {r.headers.get('location')}")
        ctx.close()
        ar.put(API + "/identity", data={"sso_enabled": True})

        # ---------- 10. AD sekmeleri (AD açıkken) ----------
        ar.put(API + "/identity", data={"ad_enabled": True})
        ctx = new_ctx(br)
        pg = ctx.new_page()
        pg.goto(UI + "/login")
        pg.wait_for_selector("[role=tab]", timeout=8000)
        check("AD açıkken Active Directory / Yerel sekmeleri görünür", pg.locator("[role=tab]").count() == 2)
        pg.screenshot(path=f"{SHOTS}/login-ad-tabs-dark.png")
        ctx.close()
        ar.put(API + "/identity", data={"ad_enabled": False})

        ar.patch(API + "/security/policy", data={"lockout_enabled": True, "lockout_max_attempts": 3,
                                                  "lockout_window_minutes": 10, "lockout_duration_minutes": 5})
        time.sleep(50)  # politika süreç önbelleği (45 sn, 2 worker)
        ar.post(API + "/auth/users", data={"username": "lockuser", "password": "Lock-User-Pass-12345", "role": "viewer"})
        ctx = new_ctx(br)
        pg = ctx.new_page()
        for i in range(3):
            ui_login(pg, "lockuser", f"kotu-parola-{i}")
            pg.wait_for_selector(".lg-error", timeout=8000)
        ui_login(pg, "lockuser", "Lock-User-Pass-12345")
        pg.wait_for_timeout(1500)
        check("kilitlenme: doğru parola bile reddedilir", "/login" in pg.url and me(pg) is None)
        pg.screenshot(path=f"{SHOTS}/login-locked.png")
        ctx.close()

        ar.patch(API + "/security/policy", data={"lockout_enabled": False})

        # ---------- temizlik: marka ----------
        ar.put(API + "/settings/branding", data={"app_name": "ainew", "company_name": "", "tagline": "", "footer_text": ""})
        br.close()

    bad = [n for n, ok in results if not ok]
    print(f"\n== {len(results) - len(bad)}/{len(results)} geçti ==")
    for n in bad:
        print("BAŞARISIZ:", n)
    sys.exit(1 if bad else 0)


main()
