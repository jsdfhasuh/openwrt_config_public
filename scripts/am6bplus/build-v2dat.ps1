param(
    [Parameter(Mandatory = $true)]
    [string]$WorkDir
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$lock = Get-Content -LiteralPath (Join-Path $repo 'configs\am6bplus\sources.lock.json') -Raw | ConvertFrom-Json
$sourceSpec = $lock.local_packages.v2dat
$commit = $sourceSpec.commit
if ($commit -notmatch '^[a-f0-9]{40}$') { throw 'Expected a pinned source commit' }
$root = [IO.Path]::GetFullPath($WorkDir)
if (Test-Path -LiteralPath $root) { throw "Refusing existing build directory: $root" }
New-Item -ItemType Directory -Path $root | Out-Null

$archiveName = 'go1.27.2.windows-amd64.zip'
$archiveSha = '1314008898bd40df77af4b014f777f08873dbdfbcd3d92308728ee03304fe04f'
$archive = Join-Path $root $archiveName
& curl.exe --fail --location --retry 2 --connect-timeout 10 --max-time 180 --output $archive "https://go.dev/dl/$archiveName"
if ($LASTEXITCODE -ne 0) { throw 'Go toolchain download failed' }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archiveSha) {
    throw 'Go toolchain checksum mismatch'
}
Expand-Archive -LiteralPath $archive -DestinationPath $root
$source = Join-Path $root 'source'
& git clone --quiet $sourceSpec.url $source
if ($LASTEXITCODE -ne 0) { throw 'Source clone failed' }
& git -C $source checkout --quiet --detach $commit
if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed' }
if ((& git -C $source rev-parse HEAD) -ne $commit) { throw 'Source commit mismatch' }

$environment = @{
    GOTOOLCHAIN = 'local'; GOPATH = (Join-Path $root 'gopath'); GOCACHE = (Join-Path $root 'gocache')
    GOPROXY = 'https://proxy.golang.org'; GOSUMDB = 'sum.golang.org'
    GOOS = 'linux'; GOARCH = 'arm64'; CGO_ENABLED = '0'
}
$previous = @{}
$go = Join-Path $root 'go\bin\go.exe'
$binary = Join-Path $root 'v2dat'
Push-Location $source
try {
    foreach ($name in $environment.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
    }
    & $go mod download
    if ($LASTEXITCODE -ne 0) { throw 'Module download failed' }
    & $go mod verify
    if ($LASTEXITCODE -ne 0) { throw 'Module verification failed' }
    & $go build -mod=readonly -trimpath '-ldflags=-s -w' -o $binary .
    if ($LASTEXITCODE -ne 0) { throw 'ARM64 build failed' }
    & $go version -m $binary
    if ($LASTEXITCODE -ne 0) { throw 'Build metadata check failed' }
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    Pop-Location
}
Get-FileHash -LiteralPath $binary -Algorithm SHA256 | Format-List
Write-Output "BINARY=$binary"
