<#
  Shared helpers for Export-ADDirectory.ps1 and ADLookup.ps1. Dot-source it; the functions read
  $Server, $PageSize, $SkipMembers and $IncludeDisabledPeople from the calling script.
#>

function Get-DomainDN([string]$fqdn) {
  ($fqdn.Split('.') | ForEach-Object { "DC=$_" }) -join ','
}

function Resolve-Method([string]$method) {
  $mode = $ExecutionContext.SessionState.LanguageMode
  $rsat = [bool](Get-Module -ListAvailable -Name ActiveDirectory)
  if ($method -ne 'Auto') { return $method }
  if ($mode -ne 'FullLanguage') {
    if (-not $rsat) {
      throw "PowerShell is in $mode mode (AppLocker/WDAC) so ADSI .NET types are blocked, and the ActiveDirectory (RSAT) module is not installed. Install RSAT, or export with your admin's tooling and drop the CSV in the ORGX inbox."
    }
    return 'RSAT'
  }
  if ($rsat) { return 'RSAT' }
  return 'ADSI'
}

# RFC 4515: escape a value placed inside an LDAP filter
function Escape-LdapValue([string]$v) {
  $v.Replace('\', '\5c').Replace('*', '\2a').Replace('(', '\28').Replace(')', '\29').Replace("`0", '\00')
}

function Escape-AdsPath([string]$dn) { $dn -replace '/', '\/' }

function New-Searcher([string]$base, [string]$filter, [string[]]$load, [string]$scope = 'Subtree', [int]$limit = 0) {
  $root = New-Object System.DirectoryServices.DirectoryEntry("LDAP://$Server/$(Escape-AdsPath $base)")
  $s = New-Object System.DirectoryServices.DirectorySearcher($root)
  $s.Filter = $filter
  $s.SearchScope = $scope
  $s.PageSize = $PageSize
  $s.ReferralChasing = 'None'
  # without this the ADSI client keeps every result of a paged search in memory
  $s.CacheResults = $false
  if ($limit) { $s.SizeLimit = $limit }
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

$Props = @(
  'displayName', 'givenName', 'sn', 'initials', 'personalTitle', 'title', 'department', 'company',
  'physicalDeliveryOfficeName', 'telephoneNumber', 'ipPhone', 'mobile', 'mail', 'userPrincipalName',
  'sAMAccountName', 'l', 'st', 'co', 'c', 'distinguishedName', 'manager', 'managedBy',
  'msExchRecipientTypeDetails', 'msExchHideFromAddressLists', 'objectGUID', 'objectClass',
  'userAccountControl', 'whenCreated', 'whenChanged', 'description', 'employeeID'
)

$Columns = @(
  'DisplayName', 'GivenName', 'Surname', 'Initials', 'Rank', 'Title', 'Department', 'Company', 'Office', 'Phone',
  'DSN', 'MobilePhone', 'WindowsEmailAddress', 'UserPrincipalName', 'SamAccountName', 'City', 'StateOrProvince',
  'CountryOrRegion', 'DistinguishedName', 'Manager', 'ManagedBy', 'Members', 'RecipientTypeDetails', 'ObjectClass',
  'ObjectGUID', 'EmployeeID', 'Enabled', 'HiddenFromAddressListsEnabled', 'WhenCreated', 'WhenChanged', 'Description'
)

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

# Rows of one search, converted, as they arrive (nothing is collected)
function Find-Rows([string]$method, [string]$base, [string]$filter, [int]$limit = 0, [string]$scope = 'Subtree') {
  $load = $Props
  if (-not $SkipMembers) { $load = $Props + 'member' }
  if ($method -eq 'RSAT') {
    Import-Module ActiveDirectory
    $q = @{ LDAPFilter = $filter; Properties = $load; SearchBase = $base; Server = $Server; ResultPageSize = $PageSize; SearchScope = $scope }
    if ($limit) { $q.ResultSetSize = $limit }
    Get-ADObject @q | ForEach-Object { Convert-Rsat $_ }
  } else {
    $s = New-Searcher $base $filter $load $scope $limit
    $res = $s.FindAll()
    try { foreach ($r in $res) { Convert-Adsi $r } } finally { $res.Dispose() }
  }
}

function Keep($row) {
  # disabled *people* are skipped; shared/room mailboxes are disabled users by design, keep them
  if ($IncludeDisabledPeople -or $row.Enabled -or $row.ObjectClass -ne 'user') { return $true }
  return ([long]("0$($row.RecipientTypeDetails)") -in 4, 16, 32, 8589934592, 17179869184, 34359738368)
}

function Format-CsvHeader { ($Columns | ForEach-Object { '"' + $_ + '"' }) -join ',' }

function Format-CsvLine($row) {
  $cells = foreach ($c in $Columns) {
    $v = $row[$c]
    if ($null -eq $v) { '""' } else { '"' + ([string]$v).Replace('"', '""') + '"' }
  }
  $cells -join ','
}
