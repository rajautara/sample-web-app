# sample-web-app

Contoh Flask webapp untuk intranet yang mengenal pasti Windows login user secara automatik (tanpa password), berjalan di belakang IIS dengan Windows Authentication.

## app9000

URL: `http://tsidsgdev01:9000`

Ciri:
- Papar user yang login (`DOMAIN\username`)
- Papar display name dan email daripada Active Directory
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

### Cara ia berfungsi

User buka `tsidsgdev01:9000`. IIS terima request dan buat Windows Authentication (Kerberos/NTLM). IIS kemudian lancarkan Flask pada port rawak di `127.0.0.1` melalui HttpPlatformHandler, dan forward token user melalui header `X-IIS-WindowsAuthToken`. `winauth.py` tukar token itu kepada `DOMAIN\username`.

Flask tidak perlu set port. IIS beri port melalui `HTTP_PLATFORM_PORT`. Jangan set Flask ke port 9000, kerana port itu milik IIS.

## Keperluan server (Windows Server 2022)

- IIS dengan Windows Authentication
- **HttpPlatformHandler v1.2 (x64)**, dipasang berasingan dari laman Microsoft IIS
- Python dipasang untuk **all users** (bukan dalam AppData)
- `pip install flask waitress pywin32`

## Deploy

Semua arahan di bawah untuk **PowerShell yang dibuka sebagai Administrator** (klik kanan Windows PowerShell, pilih *Run as administrator*, bukan versi x86).

1. Salin folder `app9000` ke `C:\inetpub\app9000`.
2. Dalam `web.config`, betulkan path `python.exe` dan nama `ADMIN_GROUP`.
3. Jalankan:

```powershell
# Pasang IIS, Windows Auth dan tool pengurusan (skip kalau sudah ada)
Install-WindowsFeature Web-Server, Web-Windows-Auth, Web-Mgmt-Console, Web-Scripting-Tools

# appcmd tiada dalam PATH, jadi buat alias
Set-Alias appcmd "$env:windir\system32\inetsrv\appcmd.exe"

# Cipta App Pool dan site
Import-Module WebAdministration
New-WebAppPool -Name app9000
Set-ItemProperty IIS:\AppPools\app9000 -Name managedRuntimeVersion -Value ""
New-Website -Name app9000 -Port 9000 -PhysicalPath C:\inetpub\app9000 -ApplicationPool app9000

# Unlock seksyen authentication (sekali sahaja per server)
appcmd unlock config -section:system.webServer/security/authentication/windowsAuthentication
appcmd unlock config -section:system.webServer/security/authentication/anonymousAuthentication

# Beri App Pool akses write ke folder app (untuk data\app.db dan logs)
icacls C:\inetpub\app9000 /grant "IIS AppPool\app9000:(OI)(CI)M"

# Buka firewall
New-NetFirewallRule -DisplayName "Flask apps" -Direction Inbound -Protocol TCP -LocalPort 9000,9001,9003 -Action Allow
```

4. Pasang HttpPlatformHandler v1.2 (x64), kemudian jalankan `iisreset`.
5. Buka `http://tsidsgdev01:9000` dari PC yang join domain.

Untuk app 9001 dan 9003, salin `winauth.py` ke folder app itu, kemudian ulang langkah cipta App Pool, site dan `icacls` dengan nama dan port yang berbeza.

### Test tanpa IIS

```
set DEV_USER=TSIDSG\nama
set DEV_DISPLAY_NAME=Nama Pengguna
set DEV_EMAIL=nama@example.com
set DEV_ADMIN=1
python app.py
```

Buka `http://localhost:5000`. `DEV_USER` diabaikan secara automatik bila app berjalan di bawah IIS.

### Display name dan email daripada Active Directory

`winauth.py` menggunakan ADSI melalui `pywin32` untuk mencari akaun
`DOMAIN\username` yang sudah disahkan oleh IIS, kemudian membaca atribut
`displayName` dan `mail`. Maklumat tersedia sebagai `g.domain`, `g.username`,
`g.display_name` dan `g.email`. `g.user` kekal sebagai kunci nota dan log akses.

Server mesti boleh menghubungi domain controller. Identiti proses App Pool perlu
akses baca AD. Pada server yang join domain, ApplicationPoolIdentity biasanya
menggunakan akaun komputer server untuk akses rangkaian; jika polisi domain
menyekatnya, gunakan identiti domain atau gMSA yang dibenarkan membaca AD.
Tidak perlu meminta password pengguna atau memberikan hak Domain Admin.

Profil dicache sehingga 5 minit bagi setiap proses. Jika carian gagal atau atribut
kosong, display name menggunakan username dan email dipaparkan sebagai
`Tidak tersedia`. Email diambil daripada `mail`, bukan diteka daripada username
atau UPN. Semak log Python dan pastikan atribut tersebut diisi dalam AD.
Uji di IIS dengan akaun domain sebenar selepas deploy; test pembangunan hanya
menggunakan `DEV_DISPLAY_NAME` dan `DEV_EMAIL` dan tidak menghubungi AD.

## Troubleshooting

### `appcmd` tidak dijumpai

`appcmd.exe` terletak di `C:\Windows\System32\inetsrv` dan tiada dalam PATH. Dalam PowerShell, `%windir%` juga tidak berfungsi (itu sintaks Command Prompt).

- Guna alias: `Set-Alias appcmd "$env:windir\system32\inetsrv\appcmd.exe"`
- Kalau fail itu tiada langsung, IIS belum dipasang. Semak dengan `Get-WindowsFeature Web-Server`.

### `Cannot read configuration file due to insufficient permission` (redirection.config)

PowerShell tidak berjalan sebagai Administrator.

- Buka semula PowerShell dengan *Run as administrator*. Jangan guna versi x86.
- Semak elevation (mesti pulangkan `True`):
  ```powershell
  ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrators")
  ```
- Kalau tetap `False`, akaun anda bukan admin di server. Minta IT jalankan arahan unlock.
- Alternatif: buang seksyen `<security>` dari `web.config`, kemudian set di IIS Manager (site > Authentication): Anonymous = Disabled, Windows = Enabled.

### HTTP Error 500.19, kod `0x8007000d`, Config Source kosong (`-1:` `0:`)

IIS tidak kenal elemen `<httpPlatform>` dalam `web.config`, bermakna **HttpPlatformHandler belum dipasang**.

- Semak:
  ```powershell
  Get-WebGlobalModule | Where-Object Name -like "*httpPlatform*"
  ```
- Kalau tiada output, pasang HttpPlatformHandler v1.2 (x64), jalankan `iisreset`, dan refresh browser.

### HTTP Error 500.19, kod `0x80070021`

Seksyen authentication masih locked. Config Source biasanya tunjuk baris `<windowsAuthentication>`. Ulang arahan `appcmd unlock` sebagai Administrator.

### HTTP Error 502.3 atau 502.5

IIS berjaya lancarkan Python tetapi app gagal start. Semak `C:\inetpub\app9000\logs\python.log`. Punca biasa:

- Path `python.exe` dalam `web.config` salah
- `flask`, `waitress` atau `pywin32` belum dipasang untuk Python yang sama
- Python dipasang dalam AppData, jadi App Pool tak boleh akses
- Folder `logs` tiada, atau App Pool tiada akses write

### Site gagal start: port sudah digunakan

Hentikan Flask lama yang masih berjalan di port 9000/9001/9003 (Task Scheduler, NSSM, atau terminal yang terbuka). Semak dengan:
```powershell
Get-NetTCPConnection -LocalPort 9000 -State Listen
```

### Browser minta username dan password

- Guna URL `http://tsidsgdev01:9000`, bukan IP address.
- Tambah `http://tsidsgdev01` ke zon **Local Intranet** (Internet Options > Security), atau minta IT push melalui Group Policy.
- Firefox: set `network.negotiate-auth.trusted-uris` kepada `tsidsgdev01`.
- PC user mesti join domain dan login dengan akaun domain.

### Halaman 401 "Login Windows tidak dikesan"

Token user tidak sampai ke Flask. Pastikan:
- `forwardWindowsAuthToken="true"` ada dalam `web.config`
- Windows Authentication Enabled dan Anonymous Authentication Disabled untuk site ini

### Halaman `/admin` beri 403 walaupun user ahli group

- Semak `ADMIN_GROUP` dalam `web.config` guna format `DOMAIN\NamaGroup`.
- User perlu logout dan login semula ke Windows selepas ditambah ke group, supaya token baru mengandungi group itu.
