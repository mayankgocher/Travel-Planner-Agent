# Run from the extracted checkpoint folder. Does not request or print keys.
$ErrorActionPreference = "Stop"
$project = "D:\Projects\GenAI\Agentic AI\Travel Planning Agent"
$source = $PSScriptRoot
if ([IO.Path]::GetFullPath($source).TrimEnd('\') -eq [IO.Path]::GetFullPath($project).TrimEnd('\')) {
    throw "Extract to a temporary folder first so installation can preserve existing files."
}
if (!(Test-Path -LiteralPath "$source\AGENTS.md" -PathType Leaf)) {
    throw "Checkpoint files are missing. Nothing was installed."
}
New-Item -ItemType Directory -Path $project -Force | Out-Null
$backup = Join-Path $project ("backup_checkpoint03_" + [guid]::NewGuid())
foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse -Force) {
    if ($file.Name -eq "INSTALL_CHECKPOINT_03.ps1") { continue }
    $relative = $file.FullName.Substring($source.Length).TrimStart('\')
    $target = Join-Path $project $relative
    if ($relative -eq ".env" -and (Test-Path -LiteralPath $target)) { continue }
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $saved = Join-Path $backup $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $saved
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
}
Write-Host "Checkpoint installed in: $project"
Write-Host "Existing .env was preserved. No venv or API keys were changed."
if (Test-Path -LiteralPath $backup) { Write-Host "Replaced files backed up in: $backup" }
Write-Host "Read README.md for interpreter verification and environment setup."
