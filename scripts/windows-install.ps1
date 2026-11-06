# Cài đặt server nhạc trên Windows: venv + thư viện + 2 Scheduled Task tự chạy khi đăng nhập.
# Chạy trong thư mục dự án:   powershell -ExecutionPolicy Bypass -File scripts\windows-install.ps1
# Tuỳ chọn:  -TunnelName notes   (tên Cloudflare Tunnel đã tạo bằng `cloudflared tunnel create`)
param(
    [string]$TunnelName = "notes"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. Python venv + thư viện
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .venv\Scripts\python -m pip install -q -U pip
& .venv\Scripts\python -m pip install -q -U -r requirements.txt
Write-Host "[ok] Đã cài thư viện Python"

# 2. Kiểm tra JS runtime cho yt-dlp
if (-not (Get-Command deno -ErrorAction SilentlyContinue) -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Warning "Chưa có deno/node, yt-dlp sẽ không giải được JS challenge. Cài: winget install DenoLand.Deno"
}

# 3. File .env
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $secret = & .venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
    (Get-Content ".env") -replace '^SESSION_SECRET=.*', "SESSION_SECRET=$secret" | Set-Content -Encoding ascii ".env"
    Write-Warning "Đã tạo .env từ .env.example. Hãy mở và điền BASE_URL, GOOGLE_*, ALLOWED_EMAILS rồi chạy lại script."
}

# 4. Scheduled Task: server
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit 0 -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$serverAction = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\pythonw.exe" `
    -Argument "-m notes" -WorkingDirectory $root
Register-ScheduledTask -TaskName "MusicServer" -Action $serverAction -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[ok] Task MusicServer"

# 5. Scheduled Task: Cloudflare Tunnel (nếu đã cấu hình)
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {  # winget cài xong nhưng PATH của phiên hiện tại chưa cập nhật
    $cf = @("${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe", "$env:ProgramFiles\cloudflared\cloudflared.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
$cfg = "$HOME\.cloudflared\config.yml"
if ($cf -and (Test-Path $cfg)) {
    $tunnelAction = New-ScheduledTaskAction -Execute $cf -Argument "tunnel --config `"$cfg`" run $TunnelName"
    Register-ScheduledTask -TaskName "MusicTunnel" -Action $tunnelAction -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "[ok] Task MusicTunnel ($TunnelName)"
} else {
    Write-Warning "Bỏ qua tunnel: chưa có cloudflared hoặc $cfg (xem README mục Cloudflare Tunnel)"
}

# 6. Khởi động
Get-ScheduledTask Music* | ForEach-Object { Stop-ScheduledTask $_.TaskName }
# pythonw của venv chỉ là launcher, tiến trình Python con vẫn giữ cổng -> tắt hẳn
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*-m notes*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
Get-ScheduledTask Music* | ForEach-Object { Start-ScheduledTask $_.TaskName }
Start-Sleep 6
try {
    $port = ((Get-Content .env | Select-String '^PORT=(\d+)').Matches.Groups[1].Value)
    if (-not $port) { $port = 8000 }
    $r = Invoke-WebRequest "http://127.0.0.1:$port/auth/config" -UseBasicParsing
    Write-Host "[ok] Server chạy ở cổng $port : $($r.Content)"
} catch {
    Write-Warning "Server chưa lên, xem server.log"
}
