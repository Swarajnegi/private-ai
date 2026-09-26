# Machine-local, regenerable voice dependencies. No cloud speech service.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = Split-Path $PSScriptRoot -Parent
$voiceRoot = Join-Path $repo '.runtime/voice'
$voiceEnv = Join-Path $repo '.venv-voice'
New-Item -ItemType Directory -Force -Path $voiceRoot | Out-Null
$env:TEMP = $voiceRoot
$env:TMP = $voiceRoot
$env:PIP_CACHE_DIR = Join-Path $repo '.cache/pip'
if (!(Test-Path "$voiceEnv/Scripts/python.exe")) {
    & "$repo/.venv/Scripts/python.exe" -m venv $voiceEnv
    if ($LASTEXITCODE) { throw 'Could not create voice environment' }
}
& "$voiceEnv/Scripts/python.exe" -m pip install 'piper-tts==1.4.2'
if ($LASTEXITCODE) { throw 'Piper install failed' }
$zip = Join-Path $voiceRoot 'whisper.zip'
$binaryDir = Join-Path $voiceRoot 'whisper'
if (!(Test-Path $binaryDir)) {
    Invoke-WebRequest 'https://github.com/ggml-org/whisper.cpp/releases/download/b5130/whisper-bin-x64.zip' -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $binaryDir
}
$whisper = Get-ChildItem $binaryDir -Filter 'whisper-cli.exe' -Recurse | Select-Object -First 1
if (!$whisper) { throw 'whisper-cli.exe was not found' }
$model = Join-Path $voiceRoot 'ggml-base.bin'
if (!(Test-Path $model)) { Invoke-WebRequest 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin' -OutFile $model }
$tts = Join-Path $voiceRoot 'en_GB-alan-medium.onnx'
$voiceURL = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium'
foreach ($file in @('en_GB-alan-medium.onnx','en_GB-alan-medium.onnx.json','MODEL_CARD')) {
    $target = Join-Path $voiceRoot $file
    if (!(Test-Path $target)) { Invoke-WebRequest "$voiceURL/$file" -OutFile $target }
}
@{whisper=$whisper.FullName;stt_model=$model;python="$voiceEnv/Scripts/python.exe";tts_model=$tts} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $voiceRoot 'config.json') -Encoding utf8
Write-Output 'Local voice installed. Audio and models stay on this machine.'
