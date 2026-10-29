# llmctl.ps1 - run llmctl from PowerShell on Windows.
#
#   .\llmctl.ps1 up
#   .\llmctl.ps1 gpu pause
#
# llmctl is a bash script. Plain `bash` in PowerShell resolves to WSL's bash.exe,
# which is not what we want, so this finds Git for Windows' bash and runs llmctl with it.

$ErrorActionPreference = 'Stop'

$candidates = @(
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
)
# Also derive it from wherever git.exe is installed (...\Git\cmd\git.exe -> ...\Git\bin\bash.exe).
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) { $candidates += Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe' }

$bash = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $bash) {
    Write-Error 'Git Bash not found. Install Git for Windows: winget install --id Git.Git -e'
    exit 1
}

& $bash (Join-Path $PSScriptRoot 'llmctl') @args
exit $LASTEXITCODE
