param(
    [ValidateRange(1024, 65535)][int]$Port = 7870,
    [switch]$Elevated
)
$ErrorActionPreference = 'Stop'
$phoneResultPath = Join-Path $PSScriptRoot 'data\runtime\launcher\phone-access-result.json'
function Write-PhoneResult($Result) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $phoneResultPath) -Force | Out-Null
    $Result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $phoneResultPath -Encoding UTF8
}
$phoneAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $phoneAdmin) {
    if ($Elevated) { throw 'Windows administrator permission is required to configure the firewall.' }
    try {
        Write-PhoneResult @{ status = 'waiting'; port = $Port }
        $phoneProcess = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -PassThru -Wait -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'), '-Port', "$Port", '-Elevated'
        )
        $phoneResult = Get-Content -LiteralPath $phoneResultPath -Raw | ConvertFrom-Json
        if ($phoneProcess.ExitCode -ne 0 -or $phoneResult.status -ne 'enabled') {
            throw "Phone access was not enabled: $($phoneResult.error) (exit $($phoneProcess.ExitCode))."
        }
        Write-Host "Phone access enabled on $($phoneResult.interfaces -join ', '), TCP port $Port."
        exit 0
    } catch {
        Write-Error $_ -ErrorAction Continue
        exit 1
    }
}
try {
    $phonePhysical = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -ExpandProperty Name)
    # Some physical adapters (such as wireless game controllers) have no IP interface.
    $phoneInterfaces = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.InterfaceAlias -in $phonePhysical -and $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)'
    } | Select-Object -ExpandProperty InterfaceAlias -Unique)
    if (-not $phoneInterfaces.Count) { throw 'Connect this computer to Wi-Fi or Ethernet first.' }
    $phoneRuleName = "LocalAtelier-LAN-TCP-$Port"
    $phoneOptions = @{
        Enabled = 'True'; Direction = 'Inbound'; Action = 'Allow'; Profile = 'Any'
        Protocol = 'TCP'; LocalPort = $Port; RemoteAddress = 'LocalSubnet'
        InterfaceAlias = $phoneInterfaces; EdgeTraversalPolicy = 'Block'
    }
    $phoneRule = Get-NetFirewallRule -Name $phoneRuleName -ErrorAction SilentlyContinue
    if ($phoneRule) {
        $phoneRule | Set-NetFirewallRule @phoneOptions
    } else {
        New-NetFirewallRule -Name $phoneRuleName -DisplayName "Local Atelier - local network ($Port)" -Description 'Local-subnet access on physical Ethernet/Wi-Fi adapters only.' @phoneOptions | Out-Null
    }
    $phoneVerified = Get-NetFirewallRule -PolicyStore ActiveStore -Name $phoneRuleName
    if ($phoneVerified.Enabled -ne 'True' -or $phoneVerified.Action -ne 'Allow') {
        throw 'The firewall rule was saved but is not enabled in the active Windows policy.'
    }
    Write-PhoneResult @{ status = 'enabled'; port = $Port; interfaces = $phoneInterfaces }
    exit 0
} catch {
    Write-PhoneResult @{ status = 'error'; port = $Port; error = $_.Exception.Message }
    exit 1
}
