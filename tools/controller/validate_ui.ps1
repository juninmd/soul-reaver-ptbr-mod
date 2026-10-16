param(
    [Parameter(Mandatory=$true)][int]$InstallerPid,
    [ValidateSet('status','select','install','remove','launch')][string]$Action='status',
    [string]$Game,
    [Parameter(Mandatory=$true)][string]$Output,
    [switch]$RuntimeAuthorized
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
$root=[System.Windows.Automation.AutomationElement]::RootElement
$scope=[System.Windows.Automation.TreeScope]::Descendants
$window=$root.FindFirst([System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$InstallerPid))
if (-not $window) { throw 'Janela do instalador não encontrada.' }
function Find-Name([string]$Name) {
    $window.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$Name))
}
function Click-Name([string]$Name) {
    $button=Find-Name $Name
    if (-not $button -or -not $button.Current.IsEnabled) { throw "Botão indisponível: $Name" }
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}
$edit=$window.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Edit))
$value=$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
if ($Action -eq 'select') {
    $candidate=[IO.Path]::GetFullPath($Game)
    $staging=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../staging'))+[IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($staging,[StringComparison]::OrdinalIgnoreCase)) { throw 'Validação automatizada exige cópia dentro de staging.' }
    $value.SetValue($candidate)
    Click-Name 'Verificar'
}
if ($Action -in @('install','remove','launch')) {
    $candidate=[IO.Path]::GetFullPath($value.Current.Value)
    $staging=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../staging'))+[IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($staging,[StringComparison]::OrdinalIgnoreCase)) { throw 'Operação automatizada fora de staging recusada.' }
    if ($Action -eq 'install') { Click-Name 'Habilitar suporte' }
    if ($Action -eq 'remove') { Click-Name 'Remover suporte' }
    if ($Action -eq 'launch') {
        if (-not $RuntimeAuthorized) { throw 'Abrir o jogo exige -RuntimeAuthorized e autorização desta rodada.' }
        Click-Name 'Jogar com DualSense'
    }
}
Start-Sleep -Milliseconds 1800
$names=@($window.FindAll($scope,[System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object { $_.Current.Name } | Where-Object { $_ })
$record=[ordered]@{timestamp=(Get-Date -Format o);action=$Action;game=$value.Current.Value;ui=$names}
$destination=[IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($destination) | Out-Null
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination "ui-$Action.json") -Encoding utf8
if ($Action -ne 'launch') {
    $support=Find-Name 'Atualizar status'
    if ($support) { try { $support.SetFocus() } catch {} }
    Start-Sleep -Milliseconds 250
    $bounds=$window.Current.BoundingRectangle
    $bitmap=[Drawing.Bitmap]::new([int]$bounds.Width,[int]$bounds.Height)
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen([int]$bounds.Left,[int]$bounds.Top,0,0,$bitmap.Size)
        $bitmap.Save((Join-Path $destination "installer-$Action.png"),[Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
}
$record | ConvertTo-Json -Depth 5
