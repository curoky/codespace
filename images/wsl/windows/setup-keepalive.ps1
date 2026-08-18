<#
.SYNOPSIS
    Fallback keep-alive for the devspace WSL distribution via a Scheduled Task.

.DESCRIPTION
    Use this when windows/wslconfig.sample (instanceIdleTimeout=-1) does not keep
    the instance running -- e.g. older WSL builds that ignore that key, or the
    WSL 2.6.x regression where even systemd services fail to keep the instance
    alive.

    It creates an at-startup task that runs, as SYSTEM, a process WSL DOES count
    as keep-alive:  wsl.exe -d <Distro> -u root -- sleep infinity
    (processes launched via wsl.exe sessions count; [boot] command processes do
    not). The task's execution time limit is disabled so the "sleep infinity"
    process is never killed after the default 3 days.

.PARAMETER Distro
    WSL distribution name. Defaults to "devspace".

.EXAMPLE
    # Run in an elevated PowerShell:
    .\setup-keepalive.ps1
    .\setup-keepalive.ps1 -Distro devspace
#>

param(
    [string]$Distro = 'devspace'
)

$ErrorActionPreference = 'Stop'

$taskName = "WSLKeepAlive-$Distro"
$wsl      = "$env:SystemRoot\System32\wsl.exe"

$action    = New-ScheduledTaskAction -Execute $wsl `
    -Argument "-d $Distro -u root -- sleep infinity"
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
    -LogonType ServiceAccount -RunLevel Highest
# ExecutionTimeLimit 0 => no limit; without this the task is stopped after 3 days.
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task '$taskName'."
Write-Host "Starting it now so '$Distro' stays running..."
Start-ScheduledTask -TaskName $taskName

Write-Host "Done. Verify with:  wsl -l -v   (should show '$Distro' Running)"
Write-Host "Remove with:        Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
