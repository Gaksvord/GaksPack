param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $repo 'tools\sync_index.py') --write
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git -C $repo add -A -- index.json packs previews
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git -C $repo diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Output 'No texture changes to publish.'; exit 0 }
git -C $repo commit -m 'Update GaksPack textures'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git -C $repo push origin main
exit $LASTEXITCODE
