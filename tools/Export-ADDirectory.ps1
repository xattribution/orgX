<#
.SYNOPSIS
  Export mail-enabled AD objects (people, org boxes, DLs, rooms, contacts) to a CSV ORGX can ingest,
  using the credentials of the logged-in user. No RSAT required.

.DESCRIPTION
  Two ways to talk to AD, picked automatically (-Method Auto):
    RSAT  Get-ADObject from the ActiveDirectory module (works in ConstrainedLanguage mode)
    ADSI  System.DirectoryServices.DirectorySearcher (built into Windows, paged, Kerberos as you)
  Every record is written to the CSV the moment it is read (results are not cached and nothing
  is collected), so memory stays flat and the file grows as the export runs, even on very large
  directories.
  Group membership larger than 1,500 values is fetched with ranged retrieval (ADSI) or ADWS (RSAT).

  -Test binds, reports who you are, which method works, the PowerShell language mode and a
  sample count, then exits without exporting. Run it first on a new machine.

.EXAMPLE
  .\Export-ADDirectory.ps1 -Test
.EXAMPLE
  .\Export-ADDirectory.ps1 -Server dc01.corp.example -SearchBase "OU=Sites,DC=corp,DC=example" -OutFile .\gal.csv
.EXAMPLE
  # nightly, straight into the ORGX inbox (ingested within a minute):
  .\Export-ADDirectory.ps1 -Inbox \\fileserver\orgx\data\inbox
#>
[CmdletBinding()]
param(
  # domain or domain controller; blank = the domain you are signed in to
  [string]$Server = '',
  # one or more search bases separated by ';' (default: the whole domain)
  [string]$SearchBase = '',
  [string]$OutFile = (Join-Path (Get-Location) ("gal_{0:yyyyMMdd_HHmm}.csv" -f (Get-Date))),
  [string]$Inbox,
  [ValidateSet('Auto', 'RSAT', 'ADSI')][string]$Method = 'Auto',
  [string]$LdapFilter = '',
  [switch]$IncludeDisabledPeople,
  [switch]$SkipMembers,
  [switch]$SkipContacts,
  [switch]$Test,
  [int]$PageSize = 1000,
  [int]$SampleSize = 25
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ADCommon.ps1')
$languageMode = $ExecutionContext.SessionState.LanguageMode
$hasRsat = [bool](Get-Module -ListAvailable -Name ActiveDirectory)

function Say([string]$s) { Write-Host $s }

$domain = $env:USERDNSDOMAIN
if (-not $Server) { $Server = $domain }
if (-not $Server) { throw "No domain: sign in to a domain, or pass -Server <domain or domain controller>." }
if (-not $SearchBase) { $SearchBase = Get-DomainDN $(if ($domain) { $domain } else { $Server }) }
$bases = @($SearchBase.Split(';') | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$classes = '(objectClass=user)(objectClass=group)'
if (-not $SkipContacts) { $classes += '(objectClass=contact)' }
if (-not $LdapFilter) { $LdapFilter = "(&(mail=*)(|$classes))" }
$Method = Resolve-Method $Method

# --------------------------------------------------------------------------- test mode
$me = [Environment]::UserName
$meDomain = [Environment]::UserDomainName
if ($Test) {
  $result = [ordered]@{ ok = $false; method = $Method; server = $Server; bases = $bases; languageMode = "$languageMode"
    rsat = $hasRsat; user = "$meDomain\$me"; userDN = ''; sample = 0; error = '' }
  try {
    $result.sample = @(Find-Rows $Method $bases[0] $LdapFilter $SampleSize).Count
    $mine = @(Find-Rows $Method $bases[0] "(sAMAccountName=$(Escape-LdapValue $me))" 1)
    if ($mine.Count) { $result.userDN = $mine[0].DistinguishedName }
    $result.ok = $true
  } catch { $result.error = $_.Exception.Message }
  Say ("RESULT " + ($result | ConvertTo-Json -Compress))
  if (-not $result.ok) { exit 2 }
  exit 0
}

# --------------------------------------------------------------------------- export
$tmp = "$OutFile.partial"
$script:count = 0
$sw = [Diagnostics.Stopwatch]::StartNew()
Say "METHOD $Method ($languageMode) as $meDomain\$me against $Server"

function Write-Rows {
  Format-CsvHeader
  foreach ($b in $bases) {
    Say "BASE $b"
    Find-Rows $Method $b $LdapFilter | ForEach-Object {
      if (Keep $_) {
        $script:count++
        if ($script:count % 5000 -eq 0) { Say ("PROGRESS {0}" -f $script:count) }
        Format-CsvLine $_
      }
    }
  }
}

# one line per record, straight to disk; Set-Content writes each line as it arrives
Write-Rows | Set-Content -Path $tmp -Encoding UTF8

Move-Item -Force $tmp $OutFile
if ($Inbox) {
  # copy under a temp name first so the server never picks up a half-written file
  $dest = Join-Path $Inbox (Split-Path $OutFile -Leaf)
  Copy-Item $OutFile "$dest.partial" -Force
  Move-Item -Force "$dest.partial" $dest
}
Say ("RESULT " + ([ordered]@{ ok = $true; method = $Method; count = $script:count; seconds = [int]$sw.Elapsed.TotalSeconds; file = $OutFile; inbox = "$Inbox" } | ConvertTo-Json -Compress))
