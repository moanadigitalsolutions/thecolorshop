param(
    [string]$OutputDir = "dist",
    [switch]$SkipMedia
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

$projectRoot = Split-Path -Parent $PSScriptRoot

if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $resolvedOutputDir = $OutputDir
}
else {
    $resolvedOutputDir = Join-Path $projectRoot $OutputDir
}

$stagingRoot = Join-Path $resolvedOutputDir "_staging"
$appStageDir = Join-Path $stagingRoot "app"
$mediaStageDir = Join-Path $stagingRoot "media"
$appZipPath = Join-Path $resolvedOutputDir "tcs-app-release.zip"
$mediaZipPath = Join-Path $resolvedOutputDir "tcs-media-bootstrap.zip"

$appItems = @(
    "config",
    "shop",
    "templates",
    "static",
    "manage.py",
    "requirements.txt",
    "README.md",
    ".env.example",
    ".env.production.example",
    "passenger_wsgi.py"
)

function Copy-ReleaseItem {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if (-not (Test-Path $SourcePath)) {
        throw "Missing release item: $SourcePath"
    }

    Copy-Item -Path $SourcePath -Destination $DestinationPath -Recurse -Force
}

function New-ReleaseArchive {
    param(
        [string]$SourceDirectory,
        [string]$DestinationPath
    )

    if (Test-Path $DestinationPath) {
        Remove-Item -Path $DestinationPath -Force
    }

    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $SourceDirectory,
        $DestinationPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}

function Remove-StagedArtifacts {
    param(
        [string]$StageDirectory
    )

    Get-ChildItem -Path $StageDirectory -Directory -Recurse -Force |
        Where-Object { $_.Name -eq "__pycache__" } |
        Remove-Item -Recurse -Force

    Get-ChildItem -Path $StageDirectory -File -Recurse -Force |
        Where-Object {
            $_.Extension -in @(".pyc", ".pyo", ".sqlite3") -or
            $_.Name -eq "db.sqlite3"
        } |
        Remove-Item -Force
}

if (-not (Test-Path $resolvedOutputDir)) {
    New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null
}

if (Test-Path $stagingRoot) {
    Remove-Item -Path $stagingRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $appStageDir -Force | Out-Null

foreach ($item in $appItems) {
    $sourcePath = Join-Path $projectRoot $item
    Copy-ReleaseItem -SourcePath $sourcePath -DestinationPath $appStageDir
}

Remove-StagedArtifacts -StageDirectory $appStageDir

if (-not (Get-ChildItem -Path $appStageDir -Force)) {
    throw "No application files were staged for packaging."
}

New-ReleaseArchive -SourceDirectory $appStageDir -DestinationPath $appZipPath
Write-Host "Created app release archive: $appZipPath"

if (-not $SkipMedia) {
    $mediaSourceDir = Join-Path $projectRoot "media"

    if (-not (Test-Path $mediaSourceDir)) {
        throw "Media directory not found: $mediaSourceDir"
    }

    New-Item -ItemType Directory -Path $mediaStageDir -Force | Out-Null

    $mediaItems = Get-ChildItem -Path $mediaSourceDir -Force

    foreach ($mediaItem in $mediaItems) {
        Copy-Item -Path $mediaItem.FullName -Destination $mediaStageDir -Recurse -Force
    }

    Remove-StagedArtifacts -StageDirectory $mediaStageDir

    if (Get-ChildItem -Path $mediaStageDir -File -Recurse -Force) {
        New-ReleaseArchive -SourceDirectory $mediaStageDir -DestinationPath $mediaZipPath
        Write-Host "Created media bootstrap archive: $mediaZipPath"
    }
    else {
        if (Test-Path $mediaZipPath) {
            Remove-Item -Path $mediaZipPath -Force
        }

        Write-Host "Media directory has no files. Skipping media bootstrap archive."
    }
}

Remove-Item -Path $stagingRoot -Recurse -Force