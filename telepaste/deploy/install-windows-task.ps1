# Registers telepaste as a Scheduled Task that starts at logon and restarts on failure.
# Untested by the author (no Windows machine); please report what breaks.
#
#   # From the light-sparkle\telepaste checkout:
#   uv tool install .              # or: pipx install .
#   mkdir $HOME\.telepaste ; copy .env.example $HOME\.telepaste\.env ; notepad $HOME\.telepaste\.env
#   powershell -ExecutionPolicy Bypass -File deploy\install-windows-task.ps1
#
# Remove with: Unregister-ScheduledTask -TaskName telepaste -Confirm:$false

$exe = (Get-Command telepaste.exe -ErrorAction Stop).Source
$envFile = Join-Path $HOME ".telepaste\.env"
$action = New-ScheduledTaskAction -Execute $exe -Argument "--env `"$envFile`" run"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "telepaste" -Action $action -Trigger $trigger -Settings $settings `
    -Description "telepaste: Telegram to clipboard and daily notes" -Force | Out-Null
Start-ScheduledTask -TaskName "telepaste"
Write-Host "telepaste task registered and started. Logs: none by default; run 'telepaste doctor' to check setup."
