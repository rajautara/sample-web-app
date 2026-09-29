"""
Modul login Windows untuk Flask di belakang IIS (HttpPlatformHandler).

IIS buat Windows Authentication, kemudian forward token user melalui header
'X-IIS-WindowsAuthToken'. Modul ini tukar token itu kepada:
  - g.user        -> "DOMAIN\\username"
  - g.username    -> "username"
  - g.is_admin    -> True kalau user ahli ADMIN_GROUP

Untuk test di PC sendiri (tanpa IIS): set DEV_USER=DOMAIN\\nama.
DEV_USER diabaikan bila app berjalan di bawah IIS.
"""
import os
from functools import wraps

from flask import abort, g, request

RUNNING_UNDER_IIS = "HTTP_PLATFORM_PORT" in os.environ


def _read_iis_token(admin_group):
    """Pulangkan (user, is_admin) daripada token IIS, atau (None, False)."""
    import win32api
    import win32security

    token_hex = request.headers.get("X-IIS-WindowsAuthToken")
    if not token_hex:
        return None, False

    handle = int(token_hex, 16)
    try:
        sid, _ = win32security.GetTokenInformation(handle, win32security.TokenUser)
        name, domain, _ = win32security.LookupAccountSid(None, sid)

        is_admin = False
        if admin_group:
            group_sid, _, _ = win32security.LookupAccountName(None, admin_group)
            groups = win32security.GetTokenInformation(handle, win32security.TokenGroups)
            is_admin = any(s == group_sid for s, _attrs in groups)

        return f"{domain}\\{name}", is_admin
    finally:
        # Wajib tutup setiap request, kalau tidak berlaku handle leak
        win32api.CloseHandle(handle)


def init_app(app):
    admin_group = app.config.get("ADMIN_GROUP", "")

    @app.before_request
    def load_windows_user():
        if RUNNING_UNDER_IIS:
            user, is_admin = _read_iis_token(admin_group)
        else:
            user = os.environ.get("DEV_USER")
            is_admin = os.environ.get("DEV_ADMIN") == "1"

        if not user:
            abort(401)

        g.user = user
        g.username = user.split("\\")[-1]
        g.is_admin = is_admin


def admin_required(view):
    """Decorator: hanya ahli ADMIN_GROUP boleh akses route ini."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapper
