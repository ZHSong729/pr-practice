# Simple checks for README.md. No extra dependencies; runs on Windows PowerShell.
# Usage: powershell -File tests/README.Tests.ps1

$readmePath = Join-Path $PSScriptRoot '..\README.md'
$failures = 0

function Test-Case([string]$name, [scriptblock]$check) {
    if (& $check) {
        Write-Host "PASS: $name"
    } else {
        Write-Host "FAIL: $name"
        $script:failures++
    }
}

Test-Case 'README.md exists' { Test-Path $readmePath }

$bytes = [IO.File]::ReadAllBytes($readmePath)
$text = [IO.File]::ReadAllText($readmePath)

Test-Case 'README.md has no UTF-8 BOM' {
    -not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
}

Test-Case 'README.md starts with the "# pr-practice" title' {
    $text -match '^# pr-practice'
}

Test-Case 'README.md does not contain the typo "Teh"' {
    $text -notmatch '\bTeh\b'
}

Test-Case 'README.md contains "The quick brown fox"' {
    $text -match 'The quick brown fox'
}

if ($failures -gt 0) {
    Write-Host "$failures test(s) failed."
    exit 1
}
Write-Host 'All tests passed.'
