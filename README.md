# sample-web-app

Contoh Flask webapp untuk intranet yang mengenal pasti Windows login user secara automatik (tanpa password), berjalan di belakang IIS dengan Windows Authentication.

## app9000

URL: `http://tsidsgdev01:9000`

Ciri:
- Papar user yang login (`DOMAIN\username`)
- Nota peribadi setiap user (SQLite)
- Halaman `/admin` untuk ahli AD group tertentu, dengan log akses

### Struktur

```
app9000/
├── app.py          # Route dan database
├── winauth.py      # Modul login Windows (guna semula untuk app lain)
├── web.config      # Konfigurasi IIS + HttpPlatformHandler
├── logs/
└── templates/
```

### Keperluan server

- Windows Server dengan IIS + Windows Authentication
- HttpPlatformHandler v1.2
- Python dipasang untuk all users
- `pip install flask waitress pywin32`

### Deploy

1. Salin folder `app9000` ke `C:\inetpub\app9000`.
2. Dalam `web.config`, betulkan path `python.exe` dan nama `ADMIN_GROUP`.
3. Cipta App Pool dan site (Command Prompt sebagai Admin):
   ```
   cd %windir%\system32\inetsrv
   appcmd add apppool /name:app9000 /managedRuntimeVersion:""
   appcmd add site /name:app9000 /bindings:http/*:9000: /physicalPath:C:\inetpub\app9000
   appcmd set app "app9000/" /applicationPool:app9000
   ```
4. Unlock seksyen authentication (sekali sahaja per server):
   ```
   appcmd unlock config -section:system.webServer/security/authentication/windowsAuthentication
   appcmd unlock config -section:system.webServer/security/authentication/anonymousAuthentication
   ```
5. Beri `IIS AppPool\app9000` akses write ke `C:\inetpub\app9000`.
6. Buka port firewall 9000.

Flask tidak perlu set port. IIS beri port rawak melalui `HTTP_PLATFORM_PORT`.

### Test tanpa IIS

```
set DEV_USER=TSIDSG\nama
set DEV_ADMIN=1
python app.py
```

Buka `http://localhost:5000`. `DEV_USER` diabaikan bila app berjalan di bawah IIS.
