# ============================================================================
# run_upsert.ps1
# End-to-end setup + run: validates .env, venv deps, Ollama model, Pinecone
# index, then upserts schema_enriched.json into Pinecone.
# ============================================================================

$ErrorActionPreference = "Stop"
$VenvPython = ".\.venv\Scripts\python.exe"
$TmpDir     = Join-Path $env:TEMP "db_agent_setup"
$TmpPy      = Join-Path $TmpDir "check_index.py"

if (-not (Test-Path -LiteralPath $TmpDir)) {
    New-Item -ItemType Directory -Path $TmpDir | Out-Null
}

function Step($n, $total, $msg) {
    Write-Host ""
    Write-Host "[$n/$total] $msg" -ForegroundColor Cyan
}
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [X] $msg" -ForegroundColor Red; exit 1 }

# ---- 1. Validate .env ------------------------------------------------------
Step 1 4 "Validating .env"
if (-not (Test-Path -LiteralPath ".env")) { Fail ".env not found in project root" }

$envRaw = Get-Content -LiteralPath ".env" -Raw
$match  = [regex]::Match($envRaw, "(?m)^\s*PINECONE_API_KEY\s*=\s*(.+?)\s*$")
if (-not $match.Success) { Fail "PINECONE_API_KEY missing in .env" }

$apiKey = $match.Groups[1].Value.Trim().Trim('"', "'")
if ([string]::IsNullOrWhiteSpace($apiKey))    { Fail "PINECONE_API_KEY is empty" }
if ($apiKey -ieq "your-pinecone-api-key-here") { Fail "PINECONE_API_KEY is still the placeholder" }
Ok "PINECONE_API_KEY present"

# ---- 2. Activate venv + verify deps ----------------------------------------
Step 2 4 "Activating virtualenv and verifying dependencies"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Fail ".venv not found. Run: python -m venv .venv"
}
Ok "venv found at $VenvPython"

$deps = @("pinecone", "python-dotenv", "ollama")
foreach ($dep in $deps) {
    & $VenvPython -m pip show $dep 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Warn "Installing missing package: $dep"
        & $VenvPython -m pip install $dep | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip install $dep failed" }
        Ok "Installed $dep"
    } else {
        Ok "$dep already installed"
    }
}

# ---- 3. Pull Ollama model --------------------------------------------------
Step 3 4 "Checking Ollama model: nomic-embed-text"
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCmd) {
    Warn "Ollama CLI not on PATH. Install from https://ollama.com/download"
    Warn "Skipping model check -- ensure 'nomic-embed-text' is pulled before running."
} else {
    & ollama list 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Warn "Cannot reach Ollama daemon. Start it: 'ollama serve'"
    } else {
        $modelList = & ollama list
        if ($modelList -match "nomic-embed-text") {
            Ok "nomic-embed-text already pulled"
        } else {
            Warn "Pulling nomic-embed-text (this may take a moment)..."
            & ollama pull nomic-embed-text
            if ($LASTEXITCODE -ne 0) { Fail "ollama pull nomic-embed-text failed" }
            Ok "nomic-embed-text ready"
        }
    }
}

# ---- 4. Validate / create Pinecone index -----------------------------------
Step 4 4 "Validating Pinecone index"

$checkPy = @'
import os, sys
from dotenv import load_dotenv
load_dotenv()
from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
idx = os.getenv("PINECONE_INDEX_NAME", "database-agent")
existing = {i.name: i for i in pc.list_indexes()}

if idx in existing:
    d = pc.describe_index(idx)
    print(f"OK {idx} dim={d.dimension} metric={d.metric}")
    if d.dimension != 768:
        print(f"BAD dim {d.dimension} != 768 (nomic-embed-text is 768d)", file=sys.stderr)
        sys.exit(2)
else:
    print(f"CREATE {idx} (dim=768, cosine, serverless aws/us-east-1)")
    pc.create_index(
        name=idx,
        dimension=768,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    print(f"OK created {idx}")
'@
Set-Content -LiteralPath $TmpPy -Value $checkPy -Encoding UTF8

& $VenvPython $TmpPy
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    if ($rc -eq 2) { Fail "Index dimension mismatch -- recreate database-agent as dim=768" }
    Fail "Pinecone index check failed"
}

# ---- Run upsert ------------------------------------------------------------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Running upsert_to_pinecone.py" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

& $VenvPython upsert_to_pinecone.py
if ($LASTEXITCODE -ne 0) { Fail "Upsert script failed" }

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  DONE - Schema upserted to Pinecone" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green