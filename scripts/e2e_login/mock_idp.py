"""Test amaçlı minimal OIDC sağlayıcı (RS256, PKCE S256, groups claim). YALNIZCA e2e testi içindir."""
import base64, hashlib, json, secrets, time
from html import escape
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn

ISSUER = "http://localhost:9180"
CLIENT_ID = "ainew-e2e"
CLIENT_SECRET = "e2e-client-secret"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "e2e-key-1"
USERS = {
    "alice":  {"name": "Alice Admin",  "email": "alice@corp.test",  "groups": ["ainew-admins"]},
    "olivia": {"name": "Olivia Ops",   "email": "olivia@corp.test", "groups": ["ainew-ops"]},
    "victor": {"name": "Victor View",  "email": "victor@corp.test", "groups": ["ainew-viewers"]},
    "nora":   {"name": "Nora NoGroup", "email": "nora@corp.test",   "groups": ["some-other-group"]},
    "localbob": {"name": "Bob (yerel hesapla cakisir)", "email": "bob@corp.test", "groups": ["ainew-admins"]},
}
CODES = {}
app = FastAPI()


def b64(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


@app.get("/.well-known/openid-configuration")
def disc():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "userinfo_endpoint": f"{ISSUER}/userinfo",
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
    }


@app.get("/jwks")
def jwks():
    pn = KEY.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": KID, "n": b64(pn.n), "e": b64(pn.e)}]}


@app.get("/authorize", response_class=HTMLResponse)
def authorize(request: Request):
    q = dict(request.query_params)
    if q.get("client_id") != CLIENT_ID or q.get("code_challenge_method") != "S256" or not q.get("nonce"):
        return HTMLResponse("bad request (client_id/PKCE/nonce)", status_code=400)
    hidden = "".join(f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in q.items())
    rows = "".join(
        f'<button name="username" value="{u}" id="pick-{u}">{u} — {escape(d["name"])} [{", ".join(d["groups"])}]</button><br>'
        for u, d in USERS.items()
    )
    return f"""<html><body style="font-family:sans-serif"><h2 id="idp-title">Mock IdP</h2>
<form method="post" action="/authorize/submit">{hidden}{rows}
<button name="username" value="__cancel__" id="pick-cancel">Iptal</button></form></body></html>"""


@app.post("/authorize/submit")
async def submit(request: Request):
    form = dict((await request.form()).items())
    redirect = form["redirect_uri"]
    state = form.get("state", "")
    if form.get("username") == "__cancel__":
        return RedirectResponse(f"{redirect}?{urlencode({'error': 'access_denied', 'error_description': '<script>alert(1)</script>', 'state': state})}", 302)
    code = secrets.token_urlsafe(24)
    CODES[code] = {"user": form["username"], "nonce": form["nonce"], "challenge": form["code_challenge"], "redirect": redirect, "exp": time.time() + 120}
    return RedirectResponse(f"{redirect}?{urlencode({'code': code, 'state': state})}", 302)


@app.post("/token")
async def token(grant_type: str = Form(...), code: str = Form(...), redirect_uri: str = Form(...),
                client_id: str = Form(...), client_secret: str = Form(...), code_verifier: str = Form(...)):
    rec = CODES.pop(code, None)
    if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
        return JSONResponse({"error": "invalid_client"}, 401)
    if not rec or rec["exp"] < time.time() or rec["redirect"] != redirect_uri:
        return JSONResponse({"error": "invalid_grant"}, 400)
    chal = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    if chal != rec["challenge"]:
        return JSONResponse({"error": "invalid_grant", "error_description": "pkce"}, 400)
    u = USERS[rec["user"]]
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": f"sub-{rec['user']}", "iat": now, "exp": now + 300,
              "nonce": rec["nonce"], "preferred_username": f"{rec['user']}@corp.test", "email": u["email"],
              "name": u["name"], "groups": u["groups"]}
    idt = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})
    return {"access_token": "at-" + secrets.token_hex(8), "token_type": "Bearer", "id_token": idt, "expires_in": 300}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9180, log_level="warning")
