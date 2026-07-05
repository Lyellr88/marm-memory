[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string[]]$Path,

    [ValidateSet('prune', 'style', 'both')]
    [string]$Mode = 'prune',

    [ValidateSet('conservative', 'launch')]
    [string]$PruneProfile = 'conservative',

    [switch]$RemoveInlineComments,
    [switch]$Apply,
    [switch]$Recurse,
    [switch]$CreateBackup,

    [int]$DividerLength = 76,

    [string[]]$KeepPattern = @(),
    [string[]]$RemovePattern = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TargetFileList {
    param(
        [string[]]$InputPath,
        [switch]$Recurse
    )

    $files = New-Object System.Collections.Generic.List[string]

    foreach ($p in $InputPath) {
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p
            if ($item.PSIsContainer) {
                $children = Get-ChildItem -LiteralPath $item.FullName -File -Recurse:$Recurse |
                    Where-Object { $_.Extension -in @('.ps1', '.psm1') }
                foreach ($child in $children) { $files.Add($child.FullName) }
            } else {
                if ($item.Extension -in @('.ps1', '.psm1')) {
                    $files.Add($item.FullName)
                }
            }
            continue
        }

        $wild = @(Get-ChildItem -Path $p -File -Recurse:$Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.ps1', '.psm1') })
        foreach ($child in $wild) { $files.Add($child.FullName) }
    }

    return @($files | Sort-Object -Unique)
}

function Get-FileContentInfo {
    param([string]$FilePath)

    $bytes = [System.IO.File]::ReadAllBytes($FilePath)
    $encodingTag = 'utf8-nobom'
    $text = $null

    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $encodingTag = 'utf8-bom'
        $enc = New-Object System.Text.UTF8Encoding($true)
        $text = $enc.GetString($bytes, 3, $bytes.Length - 3)
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $encodingTag = 'utf16le'
        $enc = [System.Text.Encoding]::Unicode
        $text = $enc.GetString($bytes, 2, $bytes.Length - 2)
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $encodingTag = 'utf16be'
        $enc = [System.Text.Encoding]::BigEndianUnicode
        $text = $enc.GetString($bytes, 2, $bytes.Length - 2)
    } else {
        try {
            $text = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($bytes)
            $encodingTag = 'utf8-nobom'
        } catch {
            $text = [System.Text.Encoding]::Default.GetString($bytes)
            $encodingTag = 'default'
        }
    }

    [pscustomobject]@{
        Text        = $text
        EncodingTag = $encodingTag
    }
}

function Set-FileContentPreserveEncoding {
    param(
        [string]$FilePath,
        [string]$Text,
        [string]$EncodingTag
    )

    switch ($EncodingTag) {
        'utf8-bom' {
            $enc = New-Object System.Text.UTF8Encoding($true)
            [System.IO.File]::WriteAllText($FilePath, $Text, $enc)
        }
        'utf16le' {
            [System.IO.File]::WriteAllText($FilePath, $Text, [System.Text.Encoding]::Unicode)
        }
        'utf16be' {
            [System.IO.File]::WriteAllText($FilePath, $Text, [System.Text.Encoding]::BigEndianUnicode)
        }
        'default' {
            [System.IO.File]::WriteAllText($FilePath, $Text, [System.Text.Encoding]::Default)
        }
        default {
            $enc = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($FilePath, $Text, $enc)
        }
    }
}

function Get-LineRecordMap {
    param([string]$Text)

    $map = @{}
    $line = 1
    $i = 0
    $len = $Text.Length

    while ($i -lt $len) {
        $start = $i
        while ($i -lt $len -and $Text[$i] -ne "`r" -and $Text[$i] -ne "`n") { $i++ }
        $contentEnd = $i

        if ($i -lt $len) {
            if ($Text[$i] -eq "`r" -and ($i + 1) -lt $len -and $Text[$i + 1] -eq "`n") {
                $i += 2
            } else {
                $i++
            }
        }
        $end = $i

        $map[$line] = [pscustomobject]@{
            Line       = $line
            Start      = $start
            ContentEnd = $contentEnd
            End        = $end
        }
        $line++
    }

    if ($len -eq 0) {
        $map[1] = [pscustomobject]@{ Line = 1; Start = 0; ContentEnd = 0; End = 0 }
    }

    return $map
}

function Test-SectionDividerLine {
    param([string]$LineText)
    return [bool]($LineText -match '^\s*#\s*=+\s*$')
}

function Get-SectionTitleMatch {
    param([string]$LineText)
    return [regex]::Match($LineText, '^(?<indent>\s*)#\s*(?<num>\d+)\.\s*(?<title>\S.*)\s*$')
}

function Test-CommentProtected {
    param(
        [string]$RawCommentText,
        [string]$FullLineText,
        [string[]]$KeepPattern,
        [switch]$KeepSectionHeaders
    )

    if ($RawCommentText -match '^\s*<#') { return $true }
    if ($FullLineText -match '^\s*#\s*(requires|region|endregion)\b') { return $true }

    if ($KeepSectionHeaders) {
        if (Test-SectionDividerLine -LineText $FullLineText) { return $true }
        $m = Get-SectionTitleMatch -LineText $FullLineText
        if ($m.Success) { return $true }
    }

    if ($FullLineText -match '^\s*#\s*(WHY|RISK|WORKAROUND|NOTE|IMPORTANT|SECURITY|COMPAT|VERSION|API|SDK|FORMAT|Brittle)\b') {
        return $true
    }

    foreach ($pat in $KeepPattern) {
        if ($RawCommentText -match $pat) { return $true }
    }

    return $false
}

function Test-LowValueComment {
    param(
        [string]$RawCommentText,
        [string]$PruneProfile,
        [bool]$IsInline,
        [string[]]$RemovePattern
    )

    foreach ($pat in $RemovePattern) {
        if ($RawCommentText -match $pat) { return $true }
    }

    if ($PruneProfile -eq 'launch') {
        return $true
    }

    $text = ($RawCommentText -replace '^\s*#+\s*', '').Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return $false }

    if ($text.Length -gt 120 -and -not $IsInline) { return $false }
    if ($text -match '[\.:;].+\s') { return $false }

    $narrationPatterns = @(
        '^(Ensure|Create|Check|Warn|Build|Parse|Write|Read|Get|Set|Run|Start|Stop|Add|Remove|Initialize|Resolve|Validate|Process|Track|Save|Load|Return)\b',
        '^Hard crashes and unclean shutdowns\b',
        '^CPU[- ]?Z\b',
        '^HWiNFO\b',
        '^GPU[- ]?Z\b'
    )
    foreach ($pattern in $narrationPatterns) {
        if ($text -match $pattern) { return $true }
    }

    if ($IsInline -and $text.Length -le 80) { return $true }

    return $false
}

function Invoke-CommentPrune {
    param(
        [string]$Text,
        [string]$PruneProfile,
        [bool]$RemoveInline,
        [string[]]$KeepPattern,
        [string[]]$RemovePattern,
        [bool]$KeepSectionHeaders
    )

    $tokenErrors = $null
    $tokens = [System.Management.Automation.PSParser]::Tokenize($Text, [ref]$tokenErrors)
    $lineMap = Get-LineRecordMap -Text $Text
    $edits = New-Object System.Collections.Generic.List[object]
    $removedStandalone = 0
    $removedInline = 0

    foreach ($tok in $tokens) {
        if ($tok.Type -ne 'Comment') { continue }
        if ($tok.Start -lt 0 -or $tok.Length -le 0) { continue }

        $raw = $Text.Substring($tok.Start, $tok.Length)
        if ($raw -match '^\s*<#') { continue }

        $lineInfo = $lineMap[$tok.StartLine]
        if (-not $lineInfo) { continue }

        $lineLength = $lineInfo.ContentEnd - $lineInfo.Start
        $lineText = if ($lineLength -gt 0) { $Text.Substring($lineInfo.Start, $lineLength) } else { '' }

        $beforeLen = $tok.Start - $lineInfo.Start
        $afterStart = $tok.Start + $tok.Length
        $afterLen = $lineInfo.ContentEnd - $afterStart
        if ($beforeLen -lt 0 -or $afterLen -lt 0) { continue }

        $before = if ($beforeLen -gt 0) { $Text.Substring($lineInfo.Start, $beforeLen) } else { '' }
        $after = if ($afterLen -gt 0) { $Text.Substring($afterStart, $afterLen) } else { '' }
        $isStandalone = ([string]::IsNullOrWhiteSpace($before) -and [string]::IsNullOrWhiteSpace($after))

        if (Test-CommentProtected -RawCommentText $raw -FullLineText $lineText -KeepPattern $KeepPattern -KeepSectionHeaders:$KeepSectionHeaders) {
            continue
        }

        $shouldRemove = Test-LowValueComment -RawCommentText $raw -PruneProfile $PruneProfile -IsInline:(-not $isStandalone) -RemovePattern $RemovePattern
        if (-not $shouldRemove) { continue }

        if ($isStandalone) {
            $edits.Add([pscustomobject]@{
                    Start = $lineInfo.Start
                    End   = $lineInfo.End
                })
            $removedStandalone++
            continue
        }

        if ($RemoveInline) {
            $editStart = $tok.Start
            while ($editStart -gt $lineInfo.Start -and ($Text[$editStart - 1] -eq ' ' -or $Text[$editStart - 1] -eq "`t")) {
                $editStart--
            }

            $edits.Add([pscustomobject]@{
                    Start = $editStart
                    End   = $tok.Start + $tok.Length
                })
            $removedInline++
        }
    }

    if ($edits.Count -eq 0) {
        return [pscustomobject]@{
            Text              = $Text
            RemovedStandalone = 0
            RemovedInline     = 0
            Changed           = $false
        }
    }

    $ordered = @($edits | Sort-Object Start, End)
    $filtered = New-Object System.Collections.Generic.List[object]
    $lastEnd = -1
    foreach ($edit in $ordered) {
        if ($edit.Start -lt $lastEnd) { continue }
        $filtered.Add($edit)
        $lastEnd = $edit.End
    }

    $sb = New-Object System.Text.StringBuilder
    $cursor = 0
    foreach ($edit in $filtered) {
        if ($edit.Start -gt $cursor) {
            [void]$sb.Append($Text.Substring($cursor, $edit.Start - $cursor))
        }
        $cursor = $edit.End
    }
    if ($cursor -lt $Text.Length) {
        [void]$sb.Append($Text.Substring($cursor))
    }

    [pscustomobject]@{
        Text              = $sb.ToString()
        RemovedStandalone = $removedStandalone
        RemovedInline     = $removedInline
        Changed           = $true
    }
}

function Get-NewlineSequence {
    param([string]$Text)
    if ($Text -match "`r`n") { return "`r`n" }
    if ($Text -match "`n") { return "`n" }
    if ($Text -match "`r") { return "`r" }
    return [Environment]::NewLine
}

function Invoke-HeaderStyleNormalization {
    param(
        [string]$Text,
        [int]$DividerLength
    )

    $newline = Get-NewlineSequence -Text $Text
    $hasTrailingNewline = ($Text.EndsWith("`r`n") -or $Text.EndsWith("`n") -or $Text.EndsWith("`r"))
    $lines = @()
    if ($Text.Length -gt 0) {
        $lines = $Text -split '\r\n|\n|\r', -1
        if ($hasTrailingNewline -and $lines.Count -gt 0 -and $lines[-1] -eq '') {
            $lines = $lines[0..($lines.Count - 2)]
        }
    }

    $outLines = New-Object System.Collections.Generic.List[string]
    $normalized = 0
    $divider = ('=' * [Math]::Max(8, $DividerLength))

    $i = 0
    while ($i -lt $lines.Count) {
        $line = $lines[$i]
        $titleMatch = Get-SectionTitleMatch -LineText $line

        if (($i + 2) -lt $lines.Count -and (Test-SectionDividerLine -LineText $lines[$i])) {
            $nextTitle = Get-SectionTitleMatch -LineText $lines[$i + 1]
            if ($nextTitle.Success -and (Test-SectionDividerLine -LineText $lines[$i + 2])) {
                $indent = $nextTitle.Groups['indent'].Value
                $num = $nextTitle.Groups['num'].Value
                $title = $nextTitle.Groups['title'].Value.Trim()
                $outLines.Add(("{0}# {1}. {2}" -f $indent, $num, $title))
                $outLines.Add(("{0}# {1}" -f $indent, $divider))
                $normalized++
                $i += 3
                continue
            }
        }

        if ($titleMatch.Success -and ($i + 1) -lt $lines.Count -and (Test-SectionDividerLine -LineText $lines[$i + 1])) {
            $indent = $titleMatch.Groups['indent'].Value
            $num = $titleMatch.Groups['num'].Value
            $title = $titleMatch.Groups['title'].Value.Trim()
            $normalizedTitle = ("{0}# {1}. {2}" -f $indent, $num, $title)
            $normalizedDivider = ("{0}# {1}" -f $indent, $divider)
            $outLines.Add($normalizedTitle)
            $outLines.Add($normalizedDivider)
            if ($lines[$i] -ne $normalizedTitle -or $lines[$i + 1] -ne $normalizedDivider) {
                $normalized++
            }
            $i += 2
            continue
        }

        $outLines.Add($line)
        $i++
    }

    $newText = [string]::Join($newline, $outLines)
    if ($hasTrailingNewline) { $newText += $newline }

    [pscustomobject]@{
        Text              = $newText
        HeadersNormalized = $normalized
        Changed           = ($newText -ne $Text)
    }
}

function Invoke-CommentsCheckFile {
    param(
        [string]$FilePath,
        [string]$Mode,
        [string]$PruneProfile,
        [bool]$RemoveInlineComments,
        [int]$DividerLength,
        [string[]]$KeepPattern,
        [string[]]$RemovePattern,
        [bool]$Apply,
        [bool]$CreateBackup
    )

    $fileInfo = Get-FileContentInfo -FilePath $FilePath
    $text = $fileInfo.Text
    $headersNormalized = 0
    $removedStandalone = 0
    $removedInline = 0

    if ($Mode -in @('style', 'both')) {
        $styleResult = Invoke-HeaderStyleNormalization -Text $text -DividerLength $DividerLength
        $text = $styleResult.Text
        $headersNormalized += $styleResult.HeadersNormalized
    }

    if ($Mode -in @('prune', 'both')) {
        $pruneResult = Invoke-CommentPrune -Text $text -PruneProfile $PruneProfile -RemoveInline:$RemoveInlineComments -KeepPattern $KeepPattern -RemovePattern $RemovePattern -KeepSectionHeaders:$true
        $text = $pruneResult.Text
        $removedStandalone += $pruneResult.RemovedStandalone
        $removedInline += $pruneResult.RemovedInline
    }

    $changed = ($text -ne $fileInfo.Text)
    if ($changed -and $Apply) {
        if ($CreateBackup) {
            Copy-Item -LiteralPath $FilePath -Destination ($FilePath + '.bak') -Force
        }
        Set-FileContentPreserveEncoding -FilePath $FilePath -Text $text -EncodingTag $fileInfo.EncodingTag
    }

    [pscustomobject]@{
        File              = $FilePath
        Changed           = $changed
        Applied           = ($changed -and $Apply)
        HeadersNormalized = $headersNormalized
        RemovedStandalone = $removedStandalone
        RemovedInline     = $removedInline
    }
}

$targets = @(Get-TargetFileList -InputPath $Path -Recurse:$Recurse)
if (@($targets).Count -eq 0) {
    throw "No PowerShell files found from path input."
}

$results = @(
foreach ($file in $targets) {
    Invoke-CommentsCheckFile -FilePath $file -Mode $Mode -PruneProfile $PruneProfile -RemoveInlineComments:$RemoveInlineComments -DividerLength $DividerLength -KeepPattern $KeepPattern -RemovePattern $RemovePattern -Apply:$Apply -CreateBackup:$CreateBackup
}
)

$changedCount = @($results | Where-Object { $_.Changed }).Count
$appliedCount = @($results | Where-Object { $_.Applied }).Count

Write-Host ""
Write-Host "Comments Check Results" -ForegroundColor Cyan
Write-Host ("  Mode: {0}  Profile: {1}" -f $Mode, $PruneProfile) -ForegroundColor DarkGray
Write-Host ("  Files: {0}  Changed: {1}  Applied: {2}" -f @($results).Count, $changedCount, $appliedCount)
Write-Host ""

foreach ($r in $results) {
    $status = if ($r.Changed) { if ($Apply) { "UPDATED" } else { "WOULD-UPDATE" } } else { "OK" }
    Write-Host ("  {0}  {1}" -f $status.PadRight(12), (Split-Path -Leaf $r.File))
    Write-Host ("    headers={0} standalone_removed={1} inline_removed={2}" -f $r.HeadersNormalized, $r.RemovedStandalone, $r.RemovedInline) -ForegroundColor DarkGray
}
