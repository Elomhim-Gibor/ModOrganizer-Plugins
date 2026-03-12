<# 
Core Physical Optimizer – Skyrim SE (MO2-Compatible, Non-Interactive, Logging Version)
This script is designed to be run from Mod Organizer 2 without running MO2 as an administrator.
It is fully automated, requires no user input, and logs all its actions to "Optimizer.log".
#>

# ---- Settings (adjust if needed) ----
$GameDir  = "$PSScriptRoot"         # Default: folder where the script is located
$Launcher = "skse64_loader.exe"     # Will fall back to SkyrimSE.exe if missing
$WaitSecs = 60                      # Maximum wait for SkyrimSE.exe to appear
# -------------------------------------

# --- Logging Setup ---
$LogFile = Join-Path $PSScriptRoot "Optimizer.log"
# Function to write to both console and log file
function Write-Log {
    param(
        [string]$Message,
        [string]$Color = "White" # Default color for console output
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    
    Write-Host $logMessage -ForegroundColor $Color
    $logMessage | Out-File -FilePath $LogFile -Append
}

# Initialize the log for this session
"------------------------------------------------------------------" | Out-File -FilePath $LogFile -Append
Write-Log -Message "MO2 Physical Core Optimizer script started." -Color Cyan
Write-Log -Message "Log file located at: $LogFile" -Color Cyan

# --- Step 1: Calculate the Affinity Mask ---
Write-Log -Message "Calculating physical core affinity..." -Color Yellow

$cpu = Get-CimInstance Win32_Processor
$cpuName       = $cpu.Name.Trim()
$logicalCores  = [int]$cpu.NumberOfLogicalProcessors
$physicalCores = [int]$cpu.NumberOfCores

# Affinity mask: assumes symmetrical multithreading (SMT) and selects even-numbered cores
$affinityMask = 0
for ($i = 0; $i -lt $logicalCores; $i += 2) { $affinityMask = $affinityMask -bor (1 -shl $i) }

Write-Log -Message "CPU: $cpuName"
Write-Log -Message "Physical Cores: $physicalCores, Logical Cores: $logicalCores"
Write-Log -Message "Calculated Affinity Mask: $affinityMask"

# --- Step 2: Launch the Game (non-elevated) ---
Write-Log -Message "Launching Skyrim via '$Launcher'..." -Color Yellow
$exePath = Join-Path $GameDir $Launcher
if (-not (Test-Path $exePath)) { $exePath = Join-Path $GameDir "SkyrimSE.exe" }

if (-not (Test-Path $exePath)) {
    Write-Log -Message "[ERROR] Executable not found in: $GameDir" -Color Red
    exit 1
}

try {
    Start-Process -FilePath $exePath -WorkingDirectory $GameDir | Out-Null
    Write-Log -Message "Successfully started the launcher."
} catch {
    Write-Log -Message "[ERROR] Failed to launch: $($_.Exception.Message)" -Color Red
    exit 1
}

# --- Step 3: Wait for the main game process to appear ---
Write-Log -Message "Waiting for SkyrimSE.exe process (max $WaitSecs seconds)..." -Color Yellow
$proc = $null
$deadline = (Get-Date).AddSeconds($WaitSecs)
while (-not $proc -and (Get-Date) -lt $deadline) {
    $proc = Get-Process -Name "SkyrimSE" -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

if (-not $proc) {
    Write-Log -Message "[ERROR] Timed out waiting for SkyrimSE.exe. The game may have crashed or took too long to start." -Color Red
    exit 1
}

Write-Log -Message "Found SkyrimSE.exe with Process ID: $($proc.Id)"

# --- Step 4: Elevate a command to apply optimizations ---
Write-Log -Message "Requesting Administrator privileges to apply optimizations..." -Color Yellow
Write-Log -Message "Please accept the UAC prompt to continue."

try {
    # This command string will be executed in the new, elevated window.
    # It logs its own actions to the same log file.
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $command = "setx DXVK_ASYNC 1 /M; Get-Process -Id $($proc.Id) | ForEach-Object { `$_.ProcessorAffinity = $affinityMask }; '[$timestamp] SUCCESS: Optimizations applied by elevated process.' | Out-File -FilePath '$LogFile' -Append"
    
    # The new elevated window will close automatically after running the command.
    Start-Process powershell -Verb RunAs -ArgumentList "-Command", "& { $command }"
    
    Write-Log -Message "Elevation request sent. Main script is finishing." -Color Green
    Write-Log -Message "The game is running. Have fun! ;-)" -Color Green

} catch {
    Write-Log -Message "[ERROR] Failed to create elevation process: $($_.Exception.Message)" -Color Red
    exit 1
}

# The main script is done and will close automatically.