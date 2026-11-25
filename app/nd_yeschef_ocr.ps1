# Yes Chef! (nd_yeschef.py): reads text from an image or PDF using the OCR engine built into Windows 10/11.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File ocr.ps1 -Path <file> [-Pdf]
# Prints the recognized text, one line per OCR line; pages separated by a blank line.
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [switch]$Pdf,
  [int]$MaxPages = 12
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskOp = $methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskAction = $methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1

function Await($op, [Type]$type) {
  $task = $asTaskOp.MakeGenericMethod($type).Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}
function AwaitAction($op) {
  $task = $asTaskAction.Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
}

[void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
[void][Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { throw 'Windows OCR is not available for your language. Add an OCR-capable language in Windows Settings.' }

function Read-Stream($stream) {
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  foreach ($line in $result.Lines) { $line.Text }
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Path).Path)) ([Windows.Storage.StorageFile])

if ($Pdf) {
  $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
  $count = [Math]::Min($doc.PageCount, $MaxPages)
  for ($i = 0; $i -lt $count; $i++) {
    $page = $doc.GetPage($i)
    $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $w = [Math]::Min(2400, [Math]::Max(1600, [int]($page.Size.Width * 2.5)))
    $opts.DestinationWidth = $w
    $mem = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    AwaitAction ($page.RenderToStreamAsync($mem, $opts))
    Read-Stream $mem
    ''
    $page.Dispose()
  }
} else {
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  Read-Stream $stream
}
