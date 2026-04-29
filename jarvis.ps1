param (
    [string]$Resume = ""
)

# JARVIS BOOTLOADER (Cloud-Only / DeepSeek V4 Pro)
# Architecture: Cloud-first, high-performance cognitive OS

# 1. ENVIRONMENT CONFIGURATION
$env:OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
$env:OPENAI_MODEL = "deepseek/deepseek-v4-pro"
$env:OPENAI_API_KEY = "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"

Write-Host "[JARVIS] Profile: OpenRouter (Cloud) | Model: deepseek-v4-pro" -ForegroundColor Green

# 2. EXECUTION LOGIC
$env:OPENCLAUDE_DIR = "E:\J.A.R.V.I.S\AI Model Reops\OpenClaude"
$env:JARVIS_WORKSPACE = "E:\J.A.R.V.I.S"

# Change to OpenClaude dir so internal build scripts work
cd $env:OPENCLAUDE_DIR

if ($Resume) {
    Write-Host "[JARVIS] Resuming session: $Resume" -ForegroundColor Cyan
    bun run scripts/provider-launch.ts openai -- --resume $Resume
}
else {
    Write-Host "[JARVIS] Launching fresh session..." -ForegroundColor Cyan
    bun run scripts/provider-launch.ts openai
}

# 3. COMMAND REFERENCE (For Copy-Paste)
# Launch fresh: .\jarvis.ps1
# Resume:       .\jarvis.ps1 -Resume <UUID>
