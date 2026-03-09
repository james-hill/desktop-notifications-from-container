param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ServiceName = "DesktopNotifyServer"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerScript = Join-Path $ScriptDir "notify_server.py"
$TaskName = $ServiceName

function Find-Python {
    $py = Get-Command python3 -ErrorAction SilentlyContinue
    if (-not $py) {
        $py = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $py) {
        Write-Error "python3/python not found. Install Python 3.10+ and try again."
        exit 1
    }
    return $py.Source
}

function Install-Service {
    $python = Find-Python
    Write-Host "Installing $ServiceName (Task Scheduler)..."
    Write-Host "  Python:  $python"
    Write-Host "  Script:  $ServerScript"

    # Remove existing task if present
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Removing existing task..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction `
        -Execute $python `
        -Argument "`"$ServerScript`"" `
        -WorkingDirectory $ScriptDir

    $trigger = New-ScheduledTaskTrigger -AtLogOn

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Seconds 10) `
        -ExecutionTimeLimit (New-TimeSpan -Duration 0)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Desktop notification server for Docker containers" `
        -RunLevel Limited | Out-Null

    # Start the task now
    Start-ScheduledTask -TaskName $TaskName

    Write-Host "Done! Service is running."
    Write-Host ""
    Write-Host "Manage with:"
    Write-Host "  Status:  Get-ScheduledTask -TaskName $TaskName"
    Write-Host "  Stop:    Stop-ScheduledTask -TaskName $TaskName"
    Write-Host "  Start:   Start-ScheduledTask -TaskName $TaskName"
    Write-Host "  Remove:  .\install.ps1 -Uninstall"
    Write-Host ""
    Write-Host "Set environment variables DESKTOP_NOTIFY_PORT and ALLOW_SOUND"
    Write-Host "in System Properties > Environment Variables to configure."
}

function Uninstall-Service {
    Write-Host "Uninstalling $ServiceName..."
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "  Task removed."
    } else {
        Write-Host "  Task not found."
    }
    Write-Host "Done."
}

if ($Uninstall) {
    Uninstall-Service
} else {
    Install-Service
}
