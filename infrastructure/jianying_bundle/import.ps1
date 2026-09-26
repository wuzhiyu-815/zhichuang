param([string]$DraftRoot = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    if (Get-Process -Name JianyingPro -ErrorAction SilentlyContinue) {
        throw '请先退出剪映专业版，再运行导入工具。'
    }
    $source = Join-Path $PSScriptRoot 'draft'
    if (!(Test-Path (Join-Path $source 'draft_content.json'))) {
        throw '请先完整解压 ZIP，再从解压后的文件夹运行导入工具。'
    }
    if (!$DraftRoot) {
        $picker = New-Object System.Windows.Forms.FolderBrowserDialog
        $picker.Description = '选择剪映全局设置中显示的草稿位置（JianyingPro Drafts），不要选择某个单独草稿'
        $default = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'
        if (Test-Path $default) { $picker.SelectedPath = $default }
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $DraftRoot = $picker.SelectedPath
    }
    $DraftRoot = (Resolve-Path -LiteralPath $DraftRoot).Path
    if ((Test-Path (Join-Path $DraftRoot 'draft_content.json')) -or (Test-Path (Join-Path $DraftRoot 'draft_meta_info.json'))) {
        throw '选中了单个草稿。请选择剪映全局设置中的草稿根目录。'
    }
    $tag = [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $folderName = '盖伦草稿_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $tag
    $target = Join-Path $DraftRoot $folderName
    if (Test-Path -LiteralPath $target) { throw '目标目录已存在，请重新运行。' }
    New-Item -ItemType Directory -Path $target | Out-Null
    Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $draftPath = $target.Replace('\', '/')
    $rootPath = $DraftRoot.Replace('\', '/')
    # Replace only our generated media-path marker, using JSON-escaped paths.
    $encodedPath = ConvertTo-Json -InputObject $draftPath -Compress
    $encodedPath = $encodedPath.Substring(1, $encodedPath.Length - 2)
    $contentFile = Join-Path $target 'draft_content.json'
    $content = [System.IO.File]::ReadAllText($contentFile)
    $content = $content.Replace('__JY_DRAFT_ROOT__', $encodedPath)
    $contentObject = $content | ConvertFrom-Json
    $newId = [Guid]::NewGuid().ToString().ToUpperInvariant()
    $content = $content.Replace($contentObject.id, $newId)
    $contentObject.id = $newId
    foreach ($material in $contentObject.materials.videos) {
        if (!(Test-Path -LiteralPath $material.path)) { throw ('素材缺失：' + $material.material_name) }
    }
    [System.IO.File]::WriteAllText($contentFile, $content, $utf8)
    $metaFile = Join-Path $target 'draft_meta_info.json'
    $meta = Get-Content -LiteralPath $metaFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $meta.draft_fold_path = $draftPath
    $meta.draft_root_path = $rootPath
    $meta.draft_id = $contentObject.id
    $meta.draft_name = $contentObject.name
    [System.IO.File]::WriteAllText($metaFile, ($meta | ConvertTo-Json -Depth 100), $utf8)
    [System.Windows.Forms.MessageBox]::Show("草稿已导入：`n$target`n`n重新打开剪映，在本地草稿中找到：$($meta.draft_name)", '导入完成') | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '导入失败') | Out-Null
    exit 1
}
