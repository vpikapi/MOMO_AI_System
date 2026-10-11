Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    Write-Host '请在 Anaconda Prompt 中按 README 激活 momo 环境后启动。'
    exit 1
}
conda run -n momo --no-capture-output python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
