"""
Modul login Windows untuk Flask di belakang IIS (HttpPlatformHandler).

IIS buat Windows Authentication, kemudian forward token user melalui header
'X-IIS-WindowsAuthToken'. Modul ini tukar token itu kepada:
  - g.user        -> "DOMAIN\\username"
  - g.username    -> "username"
  - g.domain      -> "DOMAIN"
  - g.display_name -> displayName dari Active Directory (atau username)
  - g.email       -> mail dari Active Directory (atau None)
  - g.is_admin    -> True kalau user ahli ADMIN_GROUP

Untuk test di PC sendiri (tanpa IIS): set DEV_USER=DOMAIN\\nama.
DEV_USER diabaikan bila app berjalan di bawah IIS.
"""
import os
import logging
import time
from functools import lru_cache, wraps

from flask import abort, g, request

RUNNING_UNDER_IIS = "HTTP_PLATFORM_PORT" in os.environ
logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _read_ad_profile(user, cache_period):
    """Cari akaun Windows yang disahkan dalam AD; cache selama 5 minit.

    ADSI menggunakan identiti proses App Pool untuk akses baca AD.
    Tiada password pengguna diperlukan, dan kegagalan profil tidak halang login.
    """
    if "\\" not in user:
        return None, None
    initialized = False
    translator = account = None
    try:
        import pythoncom
        import win32com.client

        # Waitress menggunakan worker threads; setiap thread perlu COM init.
        pythoncom.CoInitialize()
        initialized = True
        translator = win32com.client.Dispatch("NameTranslate")
        translator.Init(1, user.split("\\", 1)[0])  # ADS_NAME_INITTYPE_DOMAIN
        translator.Set(3, user)  # ADS_NAME_TYPE_NT4
        distinguished_name = translator.Get(1)  # ADS_NAME_TYPE_1779
        account = win32com.client.GetObject("LDAP://" + distinguished_name)

        def attribute(name):
            try:
                value = account.Get(name)
            except pythoncom.com_error:
                return None  # Atribut pilihan mungkin belum diisi dalam AD.
            return value.strip() or None if isinstance(value, str) else None

        return attribute("displayName"), attribute("mail")
    except Exception:
        logger.warning("Carian profil AD gagal; semak akses AD bagi App Pool.",
                       exc_info=True)
        return None, None
    finally:
        account = translator = None
        if initialized:
            pythoncom.CoUninitialize()


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
        g.domain = user.split("\\", 1)[0] if "\\" in user else ""
        if RUNNING_UNDER_IIS:
            display_name, email = _read_ad_profile(user, int(time.monotonic() // 300))
        else:
            display_name = os.environ.get("DEV_DISPLAY_NAME")
            email = os.environ.get("DEV_EMAIL")
        g.display_name = display_name or g.username
        g.email = email or None
        g.is_admin = is_admin


def admin_required(view):
    """Decorator: hanya ahli ADMIN_GROUP boleh akses route ini."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapper
