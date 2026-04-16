# instalar_autostart.ps1
# Registra ZenonFinder para que arranque automáticamente con Windows
# Ejecutar UNA SOLA VEZ como administrador

$taskName = "ZenonFinderBot"
$batPath = "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\start_zenonbot.bat"
$logPath = "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\logs\autostart.log"

# Crear carpeta logs si no existe
New-Item -ItemType Directory -Force -Path "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\logs" | Out-Null

# Eliminar tarea anterior si existe
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Crear la tarea
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`" >> `"$logPath`" 2>&1" `
    -WorkingDirectory "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"

$trigger = New-ScheduledTaskTrigger -AtLogon

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "ZenonFinder Bot - Auto-arranque con Windows" | Out-Null

Write-Host "✅ ZenonFinder registrado en Task Scheduler" -ForegroundColor Green
Write-Host "   Se iniciará automáticamente al hacer login en Windows"
Write-Host ""
Write-Host "Para verificar: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "Para iniciar ahora: Start-ScheduledTask -TaskName '$taskName'"
