[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Force,
    [string]$DataDirectory = '',
    [int]$DebugPort = 9323
)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$executable = Join-Path $repoRoot '.runtime\VertexStudio-latest.exe'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not $DataDirectory) { $DataDirectory = Join-Path $repoRoot '.runtime\desktop-links-preview' }
$dataRoot = [IO.Path]::GetFullPath($DataDirectory)
$connectionFile = Join-Path $dataRoot '.runtime\connection.json'
$studioConnection = $null
$restartLock = $null
$lockOwned = $false
$client = $null
$exitCode = 0

function Normalize-StudioPath([string]$Value) {
    if ($Value.StartsWith('\\?\UNC\')) { $Value = '\\' + $Value.Substring(8) }
    elseif ($Value.StartsWith('\\?\')) { $Value = $Value.Substring(4) }
    return [IO.Path]::GetFullPath($Value).TrimEnd('\')
}
function Invoke-StudioApi([string]$Method, [string]$Path) {
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $studioConnection.url.TrimEnd('/') + $Path)
    try {
        [void]$request.Headers.TryAddWithoutValidation('X-VBS-Token', [string]$studioConnection.token)
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        try {
            if (-not $response.IsSuccessStatusCode) { throw ('本地接口返回 HTTP ' + [int]$response.StatusCode) }
            $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if ($body) { $parsed = ConvertFrom-Json -InputObject $body; foreach ($item in $parsed) { Write-Output $item }; return }
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}
function Read-StudioConnection {
    $value = Get-Content -LiteralPath $connectionFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $address = [Uri]$value.url
    if ($address.Scheme -ne 'http' -or $address.Host -ne '127.0.0.1' -or $address.Query -or $address.Fragment -or $address.UserInfo -or $address.AbsolutePath -ne '/') { throw '本地连接配置无效，未执行重启。' }
    return $value
}
function Test-StudioHealth {
    try { return (Invoke-StudioApi 'GET' '/health').status -eq 'ok' } catch { return $false }
}
function Get-DebugPages {
    try {
        $response = $client.GetAsync("http://127.0.0.1:$DebugPort/json/list").GetAwaiter().GetResult()
        try { if ($response.IsSuccessStatusCode) { $parsed = ConvertFrom-Json -InputObject ($response.Content.ReadAsStringAsync().GetAwaiter().GetResult()); foreach ($item in $parsed) { Write-Output $item }; return } }
        finally { $response.Dispose() }
    } catch { return @() }
}
function Invoke-DebugExpression($Page, [string]$Expression) {
    $target = [Uri]$Page.webSocketDebuggerUrl
    if ($target.Scheme -ne 'ws' -or $target.Host -ne '127.0.0.1' -or $target.Port -ne $DebugPort) { throw '调试连接地址无效' }
    $socket = [System.Net.WebSockets.ClientWebSocket]::new()
    $timeout = [Threading.CancellationTokenSource]::new(30000)
    try {
        $socket.ConnectAsync($target, $timeout.Token).GetAwaiter().GetResult()
        $command = @{ id = 1; method = 'Runtime.evaluate'; params = @{ expression = $Expression; awaitPromise = $true; returnByValue = $true; userGesture = $true } } | ConvertTo-Json -Depth 8 -Compress
        $payload = [Text.Encoding]::UTF8.GetBytes($command)
        $socket.SendAsync([ArraySegment[byte]]::new($payload), [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $timeout.Token).GetAwaiter().GetResult()
        do {
            $stream = [IO.MemoryStream]::new()
            try {
                do {
                    $buffer = [byte[]]::new(4096)
                    $part = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $timeout.Token).GetAwaiter().GetResult()
                    if ($part.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) { throw '窗口调试连接已关闭' }
                    $stream.Write($buffer, 0, $part.Count)
                    if ($stream.Length -gt 262144) { throw '调试响应过大' }
                } while (-not $part.EndOfMessage)
                $reply = ConvertFrom-Json -InputObject ([Text.Encoding]::UTF8.GetString($stream.ToArray()))
            } finally { $stream.Dispose() }
        } while ($reply.id -ne 1)
        if ($reply.error -or $reply.result.exceptionDetails) { throw '无法读取或恢复窗口状态' }
        return $reply.result.result.value
    } finally { $socket.Dispose(); $timeout.Dispose() }
}

try {
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw '找不到 .runtime\VertexStudio-latest.exe，请先构建测试窗口。' }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '找不到项目的 .venv Python 环境。' }
    Add-Type -AssemblyName System.Net.Http
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(20)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $lockName = 'Local\VertexStudioRestart_' + ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($repoRoot.ToLowerInvariant())))).Replace('-', '').Substring(0,24) }
    finally { $hash.Dispose() }
    $restartLock = [Threading.Mutex]::new($false, $lockName)
    try { $lockOwned = $restartLock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $lockOwned = $true }
    if (-not $lockOwned) { throw '另一个重启操作正在进行，请稍后再试。' }
    $windows = @(Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($executable)) -ErrorAction SilentlyContinue | Where-Object { $_.Path -and (Normalize-StudioPath $_.Path) -eq (Normalize-StudioPath $executable) })
    if ($windows.Count -gt 1) { throw '发现多个使用同一测试程序的窗口，请先关闭多余窗口。' }
    $healthy = $false
    if (Test-Path -LiteralPath $connectionFile) {
        $studioConnection = Read-StudioConnection
        $address = [Uri]$studioConnection.url
        if ($address.Scheme -ne 'http' -or $address.Host -ne '127.0.0.1' -or $address.Query -or $address.Fragment -or $address.UserInfo -or $address.AbsolutePath -ne '/') { throw '本地连接配置无效，未执行重启。' }
        $healthy = Test-StudioHealth
    }
    if ($windows.Count -and -not $healthy -and -not $Force) { throw '无法确认当前后台状态，未执行重启。请等待窗口就绪，或使用 -Force。' }
    $reopenHarness = $false
    $offline = $false
    $active = 0
    if ($healthy) {
        $config = Invoke-StudioApi 'GET' '/config'
        if ((Normalize-StudioPath $config.root) -ne (Normalize-StudioPath $dataRoot)) { throw '后台属于其他数据目录，未执行重启。' }
        $harness = Invoke-StudioApi 'GET' '/harness/status'
        $reopenHarness = [bool]$harness.running
        $offline = [bool]$harness.offline
        $requests = @(Invoke-StudioApi 'GET' '/harness/requests')
        $active += @($requests | Where-Object { $_.phase -notin @('completed','failed','cancelled','budget_paused') }).Count
        $batches = @(Invoke-StudioApi 'GET' '/batches')
        $active += @($batches | Where-Object { $_.phase -notin @('draft','prepared','completed','completed_with_errors','failed','cancelled','upload_failed','submission_failed') }).Count
    }
    $draft = $false
    $mainPage = $null
    foreach ($page in @(Get-DebugPages)) {
        if ($page.url -like 'http://tauri.localhost/*') { $mainPage = $page }
        if ($page.url -like 'http://tauri.localhost/*' -or $page.url -like 'http://127.0.0.1:*') {
            $state = Invoke-DebugExpression $page @'
({draft:[...document.querySelectorAll('[data-composer-input][contenteditable="true"]')].some(e=>(e.innerText||'').trim().length>0)||(location.hostname==='tauri.localhost'&&[...document.querySelectorAll('textarea')].some(e=>e.value.trim().length>0))||[...document.querySelectorAll('.vbs-persona-actions button')].some(e=>e.textContent==='保存'&&!e.disabled),mode:document.documentElement.dataset.studioMode||(document.querySelector('.studio-shell')?.classList.contains('harness-mode')?'harness':null)})
'@
            if ($state.draft) { $draft = $true }
            if ($page -eq $mainPage -and $state.mode) { $reopenHarness = $state.mode -eq 'harness' }
        }
    }
    if ($CheckOnly) { Write-Host "检查完成：测试窗口 $($windows.Count) 个，未结束任务 $active 个，未保存输入 $draft。没有执行重启。"; return }
    if (($active -gt 0 -or $draft) -and -not $Force) { throw '有未结束的任务或未保存输入。请先处理；确实要重启可运行 Restart-Studio.ps1 -Force。' }
    Write-Host '正在重启测试版。会话和凭证保留，未发送内容可能丢失。'
    if ($healthy) {
        [void](Invoke-StudioApi 'POST' '/harness/stop')
        [void](Invoke-StudioApi 'POST' '/shutdown')
    }
    foreach ($window in $windows) { Stop-Process -Id $window.Id -ErrorAction SilentlyContinue }
    if ($healthy) {
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while ((Test-StudioHealth) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
        if (Test-StudioHealth) { throw '后台尚未退出，已停止操作，避免启动重复后台。' }
    }
    # Apply only a completely staged, verified preview after task/draft guards.
    $pendingExecutable = Join-Path $repoRoot '.runtime\VertexStudio-pending.exe'
    $pendingManifest = Join-Path $repoRoot '.runtime\VertexStudio-pending.json'
    if ((Test-Path -LiteralPath $pendingExecutable) -and (Test-Path -LiteralPath $pendingManifest)) {
        $pending = Get-Content -LiteralPath $pendingManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        $actualHash = (Get-FileHash -LiteralPath $pendingExecutable -Algorithm SHA256).Hash
        if ($actualHash -ne $pending.sha256) { throw '待更新程序校验失败，未替换当前程序。' }
        foreach ($oldWindow in $windows) { [void]$oldWindow.WaitForExit(10000) }
        Copy-Item -LiteralPath $pendingExecutable -Destination $executable -Force
        Write-Host '已加载经过验证的测试版更新。'
    }
    $names = @('VBS_ROOT','VBS_PYTHON','PYTHONPATH','WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')
    $previous = @{}
    foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
    try {
        $env:VBS_ROOT = $dataRoot
        $env:VBS_PYTHON = $python
        $env:PYTHONPATH = $repoRoot
        $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$DebugPort"
        $newWindow = Start-Process -FilePath $executable -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
    } finally { foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') } }
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    $ready = $false
    do {
        if (Test-Path -LiteralPath $connectionFile) {
            $studioConnection = Read-StudioConnection
            if (Test-StudioHealth) { $ready = $true; break }
        }
        if ($newWindow.HasExited) { throw '测试窗口启动失败，请查看数据目录中的 .runtime\desktop-backend.log。' }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $ready) { throw '窗口已启动，但后台尚未就绪，请查看运行日志。' }
    if ($reopenHarness) {
        $restored = $false
        do {
            $mainPage = @(Get-DebugPages | Where-Object { $_.url -like 'http://tauri.localhost/*' }) | Select-Object -First 1
            if ($mainPage) {
                $flag = if ($offline) { 'true' } else { 'false' }
                $restored = Invoke-DebugExpression $mainPage "(async()=>{const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Harness');if(!window.studio?.harnessView||!button)return false;button.click();await window.studio.harnessView(true,$flag);return true;})()"
            }
            if ($restored) { break }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $restored) { Write-Host '窗口已重开，请点击 Harness 打开页面。' }
    }
    Write-Host '重启完成。没有提交新的 Batch 任务。'
} catch {
    Write-Host ('重启未完成：' + $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($client) { $client.Dispose() }
    if ($lockOwned) { $restartLock.ReleaseMutex() }
    if ($restartLock) { $restartLock.Dispose() }
}
exit $exitCode
