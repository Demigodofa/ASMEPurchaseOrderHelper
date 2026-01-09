param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\\sectionII_partA_data_digitized"),
    [string]$ConfigPath = (Join-Path $PSScriptRoot "..\\PoApp.Ingest.Cli\\appsettings.json")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PdfFiles {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) {
        throw "Config not found: $ConfigPath"
    }

    $config = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    $pdfFiles = @()
    if ($null -ne $config.Paths.PdfFiles -and $config.Paths.PdfFiles.Count -gt 0) {
        $pdfFiles = @($config.Paths.PdfFiles | Where-Object { $_ -and $_.Trim().Length -gt 0 })
    } else {
        $root = $config.Paths.PdfSourceRoot
        if (-not $root) {
            $root = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
        }

        if (-not (Test-Path $root)) {
            throw "PDF source root not found: $root"
        }

        $pdfFiles = Get-ChildItem -Path $root -Filter "*.pdf" -File |
            Where-Object { $_.Name -match "SECT II" } |
            Where-Object { $_.Name -match "PART A" } |
            Where-Object { $_.Name -notmatch "PART B" } |
            Select-Object -ExpandProperty FullName
    }

    $existing = @()
    foreach ($path in $pdfFiles) {
        if (Test-Path $path) {
            $existing += $path
        } else {
            Write-Warning "Missing PDF file: $path"
        }
    }

    if ($existing.Count -eq 0) {
        throw "No PDF files found to digitize."
    }

    return $existing
}

function Load-PdfPig {
    param([string]$BaseDir)

    $dll = Join-Path $BaseDir "UglyToad.PdfPig.dll"
    if (-not (Test-Path $dll)) {
        throw "PdfPig not found at: $dll"
    }

    Add-Type -Path $dll
}

function Split-TableRows {
    param([string[]]$Lines)

    $tables = New-Object System.Collections.Generic.List[object]
    $current = New-Object System.Collections.Generic.List[string[]]

    foreach ($line in $Lines) {
        $trim = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trim)) {
            if ($current.Count -gt 0) {
                $tables.Add(@{ Rows = @($current) })
                $current.Clear()
            }
            continue
        }

        $cols = [System.Text.RegularExpressions.Regex]::Split($trim, "\s{2,}") |
            Where-Object { $_ -and $_.Trim().Length -gt 0 }

        if ($cols.Count -ge 3) {
            $current.Add($cols)
        } else {
            if ($current.Count -gt 0) {
                $tables.Add(@{ Rows = @($current) })
                $current.Clear()
            }
        }
    }

    if ($current.Count -gt 0) {
        $tables.Add(@{ Rows = @($current) })
        $current.Clear()
    }

    return $tables
}

function Extract-Notes {
    param([string[]]$Lines)

    $notes = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        $trim = $line.Trim()
        if ($trim -match "^(NOTE|NOTES|Note)\b") {
            $notes.Add($trim)
        }
    }

    return $notes
}

function Write-TableFiles {
    param(
        [string]$BaseName,
        [string]$TablesDir,
        [object[]]$Tables,
        [string[]]$Notes
    )

    $mdPath = Join-Path $TablesDir ("{0}.md" -f $BaseName)
    $tsvPath = Join-Path $TablesDir ("{0}.tsv" -f $BaseName)

    if ($Tables.Count -eq 0) {
        "No tables detected in pass 1." | Set-Content -Path $mdPath -Encoding UTF8
        "" | Set-Content -Path $tsvPath -Encoding UTF8
        return
    }

    $md = New-Object System.Collections.Generic.List[string]
    $tsv = New-Object System.Collections.Generic.List[string]
    $tableIndex = 1
    foreach ($table in $Tables) {
        $md.Add("## Table $tableIndex")
        $rows = $table.Rows
        if ($rows.Count -gt 0) {
            $header = $rows[0]
            $md.Add("| " + ($header -join " | ") + " |")
            $md.Add("| " + (($header | ForEach-Object { "---" }) -join " | ") + " |")
            for ($i = 1; $i -lt $rows.Count; $i++) {
                $md.Add("| " + ($rows[$i] -join " | ") + " |")
            }
            foreach ($row in $rows) {
                $tsv.Add(($row -join "`t"))
            }
        }
        $md.Add("")
        $tableIndex++
    }

    if ($Notes.Count -gt 0) {
        $md.Add("## Notes")
        foreach ($note in $Notes) {
            $md.Add("- $note")
        }
    }

    $md | Set-Content -Path $mdPath -Encoding UTF8
    $tsv | Set-Content -Path $tsvPath -Encoding UTF8
}

$pdfFiles = Resolve-PdfFiles -ConfigPath $ConfigPath
$binDir = Join-Path $PSScriptRoot "..\\PoApp.Ingest.Cli\\bin\\Debug\\net8.0"
Load-PdfPig -BaseDir $binDir

$pagesDir = Join-Path $OutputRoot "pages"
$tablesDir = Join-Path $OutputRoot "tables"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $pagesDir | Out-Null
New-Item -ItemType Directory -Force -Path $tablesDir | Out-Null

$manifest = [ordered]@{
    CreatedUtc = (Get-Date).ToUniversalTime().ToString("o")
    SourcePdfs = $pdfFiles
    OutputRoot = (Resolve-Path $OutputRoot).Path
    Pages = @()
}

$globalIndex = 1
foreach ($pdfPath in $pdfFiles) {
    Write-Host "Digitizing: $pdfPath"
    $document = [UglyToad.PdfPig.PdfDocument]::Open($pdfPath)
    foreach ($page in $document.GetPages()) {
        $text = $page.Text
        $lines = $text -replace "`r`n", "`n" -split "`n"

        $tables = Split-TableRows -Lines $lines
        $notes = Extract-Notes -Lines $lines

        $words = @()
        foreach ($word in $page.GetWords()) {
            $box = $word.BoundingBox
            $words += [ordered]@{
                text = $word.Text
                x0 = $box.Left
                y0 = $box.Bottom
                x1 = $box.Right
                y1 = $box.Top
            }
        }

        $baseName = ("page-{0:D4}" -f $globalIndex)
        $jsonPath = Join-Path $pagesDir ("{0}.json" -f $baseName)
        $txtPath = Join-Path $pagesDir ("{0}.txt" -f $baseName)

        $pageJson = [ordered]@{
            sourcePdf = (Split-Path -Leaf $pdfPath)
            sourcePageNumber = $page.Number
            globalPageIndex = $globalIndex
            width = $page.Width
            height = $page.Height
            text = $text
            words = $words
            tableCount = $tables.Count
            noteCount = $notes.Count
        }

        $pageJson | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8
        $text | Set-Content -Path $txtPath -Encoding UTF8

        Write-TableFiles -BaseName $baseName -TablesDir $tablesDir -Tables $tables -Notes $notes

        $manifest.Pages += [ordered]@{
            globalPageIndex = $globalIndex
            sourcePdf = (Split-Path -Leaf $pdfPath)
            sourcePageNumber = $page.Number
            json = ("pages/{0}.json" -f $baseName)
            text = ("pages/{0}.txt" -f $baseName)
            tablesMd = ("tables/{0}.md" -f $baseName)
            tablesTsv = ("tables/{0}.tsv" -f $baseName)
            tableCount = $tables.Count
        }

        $globalIndex++
    }
}

$manifestPath = Join-Path $OutputRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

Write-Host "Digitization complete. Output: $OutputRoot"
