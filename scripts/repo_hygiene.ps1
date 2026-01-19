param(
    [switch]$Report,
    [switch]$Apply
)

Set-StrictMode -Version Latest

function Get-GitExe {
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) {
        return $gitCmd.Source
    }

    $programFiles = $env:ProgramFiles
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $localAppData = $env:LocalAppData

    $candidates = @()
    if ($programFiles) {
        $candidates += Join-Path $programFiles "Git\cmd\git.exe"
        $candidates += Join-Path $programFiles "Git\bin\git.exe"
        $candidates += Join-Path $programFiles "Git\mingw64\bin\git.exe"
    }
    if ($programFilesX86) {
        $candidates += Join-Path $programFilesX86 "Git\cmd\git.exe"
        $candidates += Join-Path $programFilesX86 "Git\bin\git.exe"
        $candidates += Join-Path $programFilesX86 "Git\mingw64\bin\git.exe"
    }
    if ($localAppData) {
        $candidates += Join-Path $localAppData "Programs\Git\cmd\git.exe"
        $candidates += Join-Path $localAppData "Programs\Git\bin\git.exe"
        $candidates += Join-Path $localAppData "Programs\Git\mingw64\bin\git.exe"
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            Write-Host "Using git at $candidate"
            return $candidate
        }
    }

    $vsGit = Get-ChildItem -Path (Join-Path $programFiles "Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe") `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if ($vsGit) {
        Write-Host "Using git at $vsGit"
        return $vsGit
    }

    Write-Error "git executable not found in PATH or common install locations. Install git and retry."
    exit 1
}

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return ("{0:N1} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ("{0:N1} MB" -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ("{0:N1} KB" -f ($Bytes / 1KB)) }
    return ("{0} B" -f $Bytes)
}

function Get-TrackedFiles {
    param([string]$GitExe)
    $raw = & $GitExe ls-files -z
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed."
    }
    return ($raw -split [char]0 | Where-Object { $_ -and $_.Trim().Length -gt 0 })
}

function Write-Report {
    param(
        [string]$RepoRoot,
        [string]$GitExe
    )

    $tracked = Get-TrackedFiles -GitExe $GitExe
    $fileInfo = foreach ($file in $tracked) {
        $fullPath = Join-Path $RepoRoot $file
        $size = 0
        if (Test-Path -LiteralPath $fullPath) {
            $size = (Get-Item -LiteralPath $fullPath).Length
        }
        [pscustomobject]@{
            Path = $file
            SizeBytes = [long]$size
        }
    }

    $topFiles = $fileInfo | Sort-Object SizeBytes -Descending | Select-Object -First 60

    $folderSizes = @{}
    foreach ($info in $fileInfo) {
        $dir = Split-Path -Parent $info.Path
        if (-not $dir) { $dir = "." }
        if (-not $folderSizes.ContainsKey($dir)) {
            $folderSizes[$dir] = 0
        }
        $folderSizes[$dir] += $info.SizeBytes
    }

    $topFolders = $folderSizes.GetEnumerator() |
        Sort-Object Value -Descending |
        Select-Object -First 20 |
        ForEach-Object {
            [pscustomobject]@{
                Path = $_.Key
                SizeBytes = [long]$_.Value
            }
        }

    Write-Host "Top 60 tracked files by size:"
    $topFiles | Select-Object `
        @{Name="Size"; Expression={ Format-Size $_.SizeBytes }}, `
        @{Name="Bytes"; Expression={ $_.SizeBytes }}, `
        @{Name="Path"; Expression={ $_.Path }} |
        Format-Table -AutoSize

    Write-Host ""
    Write-Host "Top 20 folders by tracked size:"
    $topFolders | Select-Object `
        @{Name="Size"; Expression={ Format-Size $_.SizeBytes }}, `
        @{Name="Bytes"; Expression={ $_.SizeBytes }}, `
        @{Name="Path"; Expression={ $_.Path }} |
        Format-Table -AutoSize

    $reportPath = Join-Path $RepoRoot "repo_hygiene_report.md"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Repo Hygiene Report")
    $lines.Add("")
    $lines.Add("Generated: $timestamp")
    $lines.Add("")
    $lines.Add("## Top 60 tracked files by size")
    $lines.Add("")
    $lines.Add("| Rank | Size | Bytes | Path |")
    $lines.Add("| --- | --- | --- | --- |")
    $rank = 1
    foreach ($item in $topFiles) {
        $lines.Add("| $rank | $(Format-Size $item.SizeBytes) | $($item.SizeBytes) | $($item.Path) |")
        $rank++
    }
    $lines.Add("")
    $lines.Add("## Top 20 folders by tracked size")
    $lines.Add("")
    $lines.Add("| Rank | Size | Bytes | Path |")
    $lines.Add("| --- | --- | --- | --- |")
    $rank = 1
    foreach ($item in $topFolders) {
        $lines.Add("| $rank | $(Format-Size $item.SizeBytes) | $($item.SizeBytes) | $($item.Path) |")
        $rank++
    }

    Set-Content -LiteralPath $reportPath -Value $lines -Encoding ASCII
    Write-Host ""
    Write-Host "Saved report to $reportPath"
}

function Update-Gitignore {
    param([string]$RepoRoot)

    $gitignorePath = Join-Path $RepoRoot ".gitignore"
    $entries = @(
        "# Digitization raster/OCR caches",
        ".vs/",
        "sectionII_partA_data_digitized/full_ocr_highdpi/raster/",
        "sectionII_partA_data_digitized/raster_poppler/",
        "sectionII_partA_data_digitized/missing_target_ocr_focus/",
        "sectionII_partA_data_digitized/raster_low_conf/",
        "sectionII_partA_data_digitized/toc_raster/",
        "sectionII_partA_data_digitized/gap_ocr_highdpi/",
        "sectionII_partA_data_digitized/note_ocr_highdpi/",
        "sectionII_partA_data_digitized/tesseract_abbyy/"
    )

    $existing = @()
    if (Test-Path -LiteralPath $gitignorePath) {
        $existing = Get-Content -LiteralPath $gitignorePath
    }

    $updated = $false
    foreach ($entry in $entries) {
        if (-not ($existing -contains $entry)) {
            $existing += $entry
            $updated = $true
        }
    }

    if ($updated) {
        Set-Content -LiteralPath $gitignorePath -Value $existing -Encoding ASCII
        Write-Host "Updated .gitignore with digitization cache rules."
    } else {
        Write-Host ".gitignore already contains digitization cache rules."
    }
}

function Untrack-Paths {
    param(
        [string]$RepoRoot,
        [string]$GitExe,
        [string[]]$Paths
    )

    foreach ($path in $Paths) {
        $tracked = & $GitExe ls-files -- $path
        if ($LASTEXITCODE -ne 0) {
            throw "git ls-files failed for path: $path"
        }
        if (-not $tracked) {
            continue
        }
        Write-Host "Untracking $path"
        & $GitExe rm -r --cached -- $path
        if ($LASTEXITCODE -ne 0) {
            throw "git rm --cached failed for path: $path"
        }
    }
}

if (-not $Report -and -not $Apply) {
    Write-Host "Usage: .\\scripts\\repo_hygiene.ps1 -Report | -Apply"
    exit 1
}

$gitExe = Get-GitExe
$repoRoot = & $gitExe rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    Write-Error "Current directory is not inside a git repository."
    exit 1
}

Set-Location $repoRoot

if ($Report) {
    Write-Report -RepoRoot $repoRoot -GitExe $gitExe
}

if ($Apply) {
    Write-Host "Git status (before):"
    & $gitExe status --short

    Update-Gitignore -RepoRoot $repoRoot

    $pathsToUntrack = @(
        ".vs/",
        "sectionII_partA_data_digitized/full_ocr_highdpi/raster/",
        "sectionII_partA_data_digitized/raster_poppler/",
        "sectionII_partA_data_digitized/missing_target_ocr_focus/",
        "sectionII_partA_data_digitized/raster_low_conf/",
        "sectionII_partA_data_digitized/toc_raster/",
        "sectionII_partA_data_digitized/gap_ocr_highdpi/",
        "sectionII_partA_data_digitized/note_ocr_highdpi/",
        "sectionII_partA_data_digitized/tesseract_abbyy/"
    )

    Untrack-Paths -RepoRoot $repoRoot -GitExe $gitExe -Paths $pathsToUntrack

    & $gitExe add .gitignore

    Write-Host "Git status (after):"
    & $gitExe status --short

    & $gitExe diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "No staged changes to commit."
    } else {
        & $gitExe commit -m "Stop tracking digitization raster caches; ignore generated artifacts."
    }
}
