<#
.SYNOPSIS
  Export mail-enabled AD objects (people, org boxes, DLs, rooms, contacts) to a CSV ORGX can ingest,
  using the credentials of the logged-in user. No RSAT required.

.DESCRIPTION
  Two ways to talk to AD, picked automatically (-Method Auto):
    RSAT  Get-ADObject from the ActiveDirectory module (works in ConstrainedLanguage mode)
    ADSI  System.DirectoryServices.DirectorySearcher (built into Windows, paged, Kerberos as you)
  Both stream rows to Export-Csv, so memory stays flat on very large directories.
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
$languageMode = $ExecutionContext.SessionState.LanguageMode
$hasRsat = [bool](Get-Module -ListAvailable -Name ActiveDirectory)

function Say([string]$s) { Write-Host $s }

function Get-DomainDN([string]$fqdn) {
  ($fqdn.Split('.') | ForEach-Object { "DC=$_" }) -join ','
}

$domain = $env:USERDNSDOMAIN
if (-not $Server) { $Server = $domain }
if (-not $Server) { throw "No domain: sign in to a domain, or pass -Server <domain or domain controller>." }
if (-not $SearchBase) { $SearchBase = Get-DomainDN $(if ($domain) { $domain } else { $Server }) }
$bases = @($SearchBase.Split(';') | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$classes = '(objectClass=user)(objectClass=group)'
if (-not $SkipContacts) { $classes += '(objectClass=contact)' }
if (-not $LdapFilter) { $LdapFilter = "(&(mail=*)(|$classes))" }

$props = @(
  'displayName', 'givenName', 'sn', 'initials', 'personalTitle', 'title', 'department', 'company',
  'physicalDeliveryOfficeName', 'telephoneNumber', 'ipPhone', 'mobile', 'mail', 'userPrincipalName',
  'sAMAccountName', 'l', 'st', 'co', 'c', 'distinguishedName', 'manager', 'managedBy',
  'msExchRecipientTypeDetails', 'msExchHideFromAddressLists', 'objectGUID', 'objectClass',
  'userAccountControl', 'whenCreated', 'whenChanged', 'description', 'employeeID'
)
if (-not $SkipMembers) { $props += 'member' }

# --------------------------------------------------------------------------- method
if ($Method -eq 'Auto') {
  if ($languageMode -ne 'FullLanguage') {
    if (-not $hasRsat) {
      throw "PowerShell is in $languageMode mode (AppLocker/WDAC) so ADSI .NET types are blocked, and the ActiveDirectory (RSAT) module is not installed. Install RSAT, or export with AD Explorer / your admin's tooling and drop the CSV in the ORGX inbox."
    }
    $Method = 'RSAT'
  } elseif ($hasRsat) { $Method = 'RSAT' } else { $Method = 'ADSI' }
}

# --------------------------------------------------------------------------- ADSI helpers
function Escape-AdsPath([string]$dn) { $dn -replace '/', '\/' }

function New-Searcher([string]$base, [string]$filter, [string[]]$load, [string]$scope = 'Subtree') {
  $root = New-Object System.DirectoryServices.DirectoryEntry("LDAP://$Server/$(Escape-AdsPath $base)")
  $s = New-Object System.DirectoryServices.DirectorySearcher($root)
  $s.Filter = $filter
  $s.SearchScope = $scope
  $s.PageSize = $PageSize
  $s.ReferralChasing = 'None'
  foreach ($p in $load) { [void]$s.PropertiesToLoad.Add($p) }
  $s
}

function First($r, [string]$name) {
  $v = $r.Properties[$name.ToLower()]
  if ($v -and $v.Count -gt 0) { $v[0] } else { $null }
}

function Get-RangedMembers([string]$dn) {
  $all = New-Object System.Collections.Generic.List[string]
  $lo = 0
  while ($true) {
    $attr = "member;range=$lo-*"
    $s = New-Searcher $dn '(objectClass=*)' @($attr) 'Base'
    $r = $s.FindOne()
    if (-not $r) { break }
    $key = @($r.Properties.PropertyNames | Where-Object { $_ -like 'member;range=*' })[0]
    if (-not $key) { break }
    foreach ($m in $r.Properties[$key]) { $all.Add([string]$m) }
    if ($key -like '*-`*') { break }
    $lo = $all.Count
  }
  $all
}

function Convert-Adsi($r) {
  $classes = @($r.Properties['objectclass'])
  $cls = if ($classes.Count) { $classes[$classes.Count - 1] } else { '' }
  $uac = [int](First $r 'userAccountControl')
  $enabled = if ($cls -eq 'user') { -not ($uac -band 2) } else { $true }
  $members = ''
  if (-not $SkipMembers) {
    $ranged = @($r.Properties.PropertyNames | Where-Object { $_ -like 'member;range=*' })
    if ($ranged.Count) { $members = (Get-RangedMembers (First $r 'distinguishedName')) -join ';' }
    elseif ($r.Properties['member']) { $members = (@($r.Properties['member']) -join ';') }
  }
  $guidBytes = First $r 'objectGUID'
  [ordered]@{
    DisplayName = First $r 'displayName'; GivenName = First $r 'givenName'; Surname = First $r 'sn'
    Initials = First $r 'initials'; Rank = First $r 'personalTitle'; Title = First $r 'title'
    Department = First $r 'department'; Company = First $r 'company'; Office = First $r 'physicalDeliveryOfficeName'
    Phone = First $r 'telephoneNumber'; DSN = First $r 'ipPhone'; MobilePhone = First $r 'mobile'
    WindowsEmailAddress = First $r 'mail'; UserPrincipalName = First $r 'userPrincipalName'
    SamAccountName = First $r 'sAMAccountName'; City = First $r 'l'; StateOrProvince = First $r 'st'
    CountryOrRegion = $(if (First $r 'co') { First $r 'co' } else { First $r 'c' })
    DistinguishedName = First $r 'distinguishedName'; Manager = First $r 'manager'; ManagedBy = First $r 'managedBy'
    Members = $members; RecipientTypeDetails = First $r 'msExchRecipientTypeDetails'; ObjectClass = $cls
    ObjectGUID = $(if ($guidBytes) { (New-Object Guid (, [byte[]]$guidBytes)).ToString() } else { '' })
    EmployeeID = First $r 'employeeID'; Enabled = $enabled
    HiddenFromAddressListsEnabled = [bool](First $r 'msExchHideFromAddressLists')
    WhenCreated = $(if (First $r 'whenCreated') { (First $r 'whenCreated').ToString('s') } else { '' })
    WhenChanged = $(if (First $r 'whenChanged') { (First $r 'whenChanged').ToString('s') } else { '' })
    Description = (@($r.Properties['description']) -join ' ')
  }
}

# --------------------------------------------------------------------------- RSAT helper
function Convert-Rsat($o) {
  $uac = [int]($o.userAccountControl | Select-Object -First 1)
  $enabled = if ($o.objectClass -eq 'user') { -not ($uac -band 2) } else { $true }
  [ordered]@{
    DisplayName = $o.displayName; GivenName = $o.givenName; Surname = $o.sn; Initials = $o.initials
    Rank = $o.personalTitle; Title = $o.title; Department = $o.department; Company = $o.company
    Office = $o.physicalDeliveryOfficeName; Phone = $o.telephoneNumber; DSN = $o.ipPhone; MobilePhone = $o.mobile
    WindowsEmailAddress = $o.mail; UserPrincipalName = $o.userPrincipalName; SamAccountName = $o.sAMAccountName
    City = $o.l; StateOrProvince = $o.st; CountryOrRegion = $(if ($o.co) { $o.co } else { $o.c })
    DistinguishedName = $o.distinguishedName; Manager = $o.manager; ManagedBy = $o.managedBy
    Members = $(if ($SkipMembers -or -not $o.member) { '' } else { ($o.member -join ';') })
    RecipientTypeDetails = $o.msExchRecipientTypeDetails; ObjectClass = $o.objectClass
    ObjectGUID = "$($o.objectGUID)"; EmployeeID = $o.employeeID; Enabled = $enabled
    HiddenFromAddressListsEnabled = [bool]$o.msExchHideFromAddressLists
    WhenCreated = $(if ($o.whenCreated) { $o.whenCreated.ToString('s') } else { '' })
    WhenChanged = $(if ($o.whenChanged) { $o.whenChanged.ToString('s') } else { '' })
    Description = ($o.description -join ' ')
  }
}

function Get-Rows([string]$base, [int]$limit = 0) {
  if ($Method -eq 'RSAT') {
    Import-Module ActiveDirectory
    $q = @{ LDAPFilter = $LdapFilter; Properties = $props; SearchBase = $base; Server = $Server; ResultPageSize = $PageSize }
    if ($limit) { $q.ResultSetSize = $limit }
    Get-ADObject @q | ForEach-Object { Convert-Rsat $_ }
  } else {
    $s = New-Searcher $base $LdapFilter $props
    if ($limit) { $s.SizeLimit = $limit }
    $res = $s.FindAll()
    try { foreach ($r in $res) { Convert-Adsi $r } } finally { $res.Dispose() }
  }
}

function Keep($row) {
  # disabled *people* are skipped; shared/room mailboxes are disabled users by design, keep them
  if ($IncludeDisabledPeople -or $row.Enabled -or $row.ObjectClass -ne 'user') { return $true }
  return ([long]("0$($row.RecipientTypeDetails)") -in 4, 16, 32, 8589934592, 17179869184, 34359738368)
}

# --------------------------------------------------------------------------- test mode
$me = [Environment]::UserName
$meDomain = [Environment]::UserDomainName
if ($Test) {
  $result = [ordered]@{ ok = $false; method = $Method; server = $Server; bases = $bases; languageMode = "$languageMode"
    rsat = $hasRsat; user = "$meDomain\$me"; userDN = ''; sample = 0; error = '' }
  try {
    $result.sample = @(Get-Rows $bases[0] $SampleSize).Count
    if ($Method -eq 'ADSI') {
      $s = New-Searcher $bases[0] "(sAMAccountName=$me)" @('distinguishedName')
      $hit = $s.FindOne()
      if ($hit) { $result.userDN = First $hit 'distinguishedName' }
    } else {
      $result.userDN = (Get-ADUser -Identity $me -Server $Server).DistinguishedName
    }
    $result.ok = $true
  } catch { $result.error = $_.Exception.Message }
  Say ("RESULT " + ($result | ConvertTo-Json -Compress))
  if (-not $result.ok) { exit 2 }
  exit 0
}

# --------------------------------------------------------------------------- export
$tmp = "$OutFile.partial"
$count = 0
$sw = [Diagnostics.Stopwatch]::StartNew()
Say "METHOD $Method ($languageMode) as $meDomain\$me against $Server"
& {
  foreach ($b in $bases) {
    Say "BASE $b"
    Get-Rows $b | Where-Object { Keep $_ } | ForEach-Object {
      $script:count++
      if ($script:count % 5000 -eq 0) { Say ("PROGRESS {0}" -f $script:count) }
      [pscustomobject]$_
    }
  }
} | Export-Csv -Path $tmp -NoTypeInformation -Encoding UTF8

Move-Item -Force $tmp $OutFile
if ($Inbox) {
  # copy under a temp name first so the server never picks up a half-written file
  $dest = Join-Path $Inbox (Split-Path $OutFile -Leaf)
  Copy-Item $OutFile "$dest.partial" -Force
  Move-Item -Force "$dest.partial" $dest
}
Say ("RESULT " + ([ordered]@{ ok = $true; method = $Method; count = $count; seconds = [int]$sw.Elapsed.TotalSeconds; file = $OutFile; inbox = "$Inbox" } | ConvertTo-Json -Compress))
