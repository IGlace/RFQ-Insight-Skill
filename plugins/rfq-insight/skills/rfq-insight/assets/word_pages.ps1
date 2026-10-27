param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$rfqWord = $null
$rfqDocument = $null
$rfqOwned = $false
$rfqBefore = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | ForEach-Object Id)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class RfqWordWindow {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
}
'@
try {
    $rfqWord = New-Object -ComObject Word.Application
    $rfqWord.Visible = $false
    $rfqWord.DisplayAlerts = 0
    $rfqWord.AutomationSecurity = 3
    $rfqDocument = $rfqWord.Documents.Open($Source, $false, $true, $false)
    [uint32]$rfqProcessId = 0
    [void][RfqWordWindow]::GetWindowThreadProcessId([IntPtr]$rfqDocument.ActiveWindow.Hwnd, [ref]$rfqProcessId)
    $rfqProcess = Get-Process -Id $rfqProcessId -ErrorAction Stop
    if ($rfqProcessId -eq 0 -or $rfqProcessId -in $rfqBefore -or $rfqProcess.ProcessName -ne 'WINWORD') {
        throw 'A private Word process could not be established.'
    }
    $rfqOwned = $true
    Set-Content -LiteralPath (Join-Path (Split-Path $Output) 'word.pid') -Value $rfqProcessId
    $rfqDocument.Repaginate()
    $rfqBlocks = @()
    $rfqTables = @{}
    foreach ($rfqParagraph in $rfqDocument.Paragraphs) {
        $rfqRange = $rfqParagraph.Range
        if ($rfqRange.Information(12)) {
            $rfqTable = $rfqRange.Tables.Item(1)
            $rfqIdentity = [string]$rfqTable.Range.Start
            if ($rfqTables.ContainsKey($rfqIdentity)) { continue }
            $rfqTables[$rfqIdentity] = $true
            $rfqRange = $rfqTable.Range.Duplicate
            $rfqKind = 'table'
        } else { $rfqKind = 'paragraph' }
        $rfqFirst = $rfqRange.Duplicate
        $rfqFirst.Collapse(1)
        $rfqLast = $rfqRange.Duplicate
        [void]$rfqLast.MoveEnd(1, -1)
        $rfqLast.Collapse(0)
        $rfqBlocks += @{ kind=$rfqKind; start_page=[int]$rfqFirst.Information(3);
                        end_page=[int]$rfqLast.Information(3) }
    }
    @{ method='Microsoft Word rendered pagination';
       source_sha256=(Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant();
       pages=[int]$rfqDocument.ComputeStatistics(2); blocks=$rfqBlocks } |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Output -Encoding utf8
} finally {
    if ($rfqDocument) { $rfqDocument.Close(0); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($rfqDocument) }
    if ($rfqWord) {
        if ($rfqOwned) { $rfqWord.Quit() }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($rfqWord)
    }
}
