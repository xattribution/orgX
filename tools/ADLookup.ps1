<#
.SYNOPSIS
  On-the-fly lookups for ORGX: small, targeted Active Directory searches as the logged-in user.

.DESCRIPTION
  ORGX runs this with -Serve and keeps it open. Each request is one JSON line on stdin:
    {"id": 7, "ops": [{"op": "search", "term": "doe", "limit": 25}, {"op": "reports", "dn": "CN=…", "limit": 100}]}
  and each reply is one line on stdout:
    REPLY {"id": 7, "results": [[row, …], [row, …]], "error": ""}
  Rows use the same columns as Export-ADDirectory.ps1, so ORGX reads them the same way.

  Operations
    search   ambiguous name resolution (anr=), the same matching the Outlook address book uses
    dn       fetch objects by distinguished name ("dns": [...])
    reports  objects whose manager is "dn"
    dept     objects whose department is "value" or starts with "value/"
    ous      organizational units whose name starts with "term" (DNs only)
    ou       objects under the OU "base"

  Where PowerShell can't read stdin line by line (Constrained Language mode), ORGX calls it once
  per request with -Request <file> instead.
#>
[CmdletBinding()]
param(
  [string]$Server = '',
  [ValidateSet('Auto', 'RSAT', 'ADSI')][string]$Method = 'Auto',
  [int]$PageSize = 500,
  [switch]$Serve,
  [string]$Request
)

$ErrorActionPreference = 'Stop'
$SkipMembers = $true                 # membership is not fetched on the fly
$IncludeDisabledPeople = $false
. (Join-Path $PSScriptRoot 'ADCommon.ps1')

function Say([string]$s) { Write-Host $s }

$domain = $env:USERDNSDOMAIN
if (-not $Server) { $Server = $domain }
$Method = Resolve-Method $Method
$root = Get-DomainDN $(if ($domain) { $domain } else { $Server })
$mailObjects = '(mail=*)(|(objectClass=user)(objectClass=group)(objectClass=contact))'

function Lim($op, [int]$d) { if ($op.limit) { [int]$op.limit } else { $d } }

# OU names are not covered by anr, so a search for a site looks for its OU separately
function Find-Ous([string]$term, [int]$limit) {
  $filter = "(&(objectClass=organizationalUnit)(ou=$(Escape-LdapValue $term)*))"
  if ($Method -eq 'RSAT') {
    Import-Module ActiveDirectory
    Get-ADObject -LDAPFilter $filter -SearchBase $root -Server $Server -ResultSetSize $limit |
      ForEach-Object { [ordered]@{ DistinguishedName = $_.DistinguishedName; ObjectClass = 'organizationalUnit' } }
  } else {
    $s = New-Searcher $root $filter @('distinguishedName') 'Subtree' $limit
    $res = $s.FindAll()
    try { foreach ($r in $res) { [ordered]@{ DistinguishedName = First $r 'distinguishedName'; ObjectClass = 'organizationalUnit' } } } finally { $res.Dispose() }
  }
}

function Invoke-Op($op) {
  switch ($op.op) {
    'search' {
      Find-Rows $Method $root "(&$mailObjects(anr=$(Escape-LdapValue ([string]$op.term))))" (Lim $op 25)
    }
    'dn' {
      $dns = @($op.dns)
      for ($i = 0; $i -lt $dns.Count; $i += 20) {
        $part = $dns[$i..([Math]::Min($i + 19, $dns.Count - 1))] | ForEach-Object { "(distinguishedName=$(Escape-LdapValue $_))" }
        Find-Rows $Method $root "(|$($part -join ''))" 0
      }
    }
    'reports' {
      Find-Rows $Method $root "(&$mailObjects(manager=$(Escape-LdapValue ([string]$op.dn))))" (Lim $op 100)
    }
    'dept' {
      $v = Escape-LdapValue ([string]$op.value)
      Find-Rows $Method $root "(&$mailObjects(|(department=$v)(department=$v/*)))" (Lim $op 300)
    }
    'ous' {
      Find-Ous ([string]$op.term) (Lim $op 10)
    }
    'ou' {
      Find-Rows $Method ([string]$op.base) "(&$mailObjects)" (Lim $op 400)
    }
    default { throw "unknown op $($op.op)" }
  }
}

function Invoke-Request($req) {
  $out = [ordered]@{ id = $req.id; results = @(); error = '' }
  try {
    $out.results = @(foreach ($op in @($req.ops)) { , @(Invoke-Op $op | Where-Object { Keep $_ }) })
  } catch { $out.error = $_.Exception.Message }
  "REPLY " + (ConvertTo-Json -InputObject $out -Depth 6 -Compress)
}

if ($Request) {
  Say (Invoke-Request (Get-Content -Raw -Path $Request | ConvertFrom-Json))
  exit 0
}

if ($Serve) {
  try { $in = [Console]::In } catch { Say "NOSERVE"; exit 3 }
  Say ("READY " + ([ordered]@{ method = $Method; server = $Server; root = $root } | ConvertTo-Json -Compress))
  while ($null -ne ($line = $in.ReadLine())) {
    if (-not $line.Trim()) { continue }
    Say (Invoke-Request ($line | ConvertFrom-Json))
  }
  exit 0
}

Say "Use -Serve (ORGX keeps it open) or -Request <file.json>."
exit 1
