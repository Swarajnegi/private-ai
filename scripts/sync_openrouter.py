import urllib.request
import json
import os
import sys
import time
from pathlib import Path

# NOTE (Stage 4.3.3): catalog path now resolves cross-platform via jarvis_core.config
# (it used to hardcode E:\...) -- the same fix suggest_model.py got earlier this session.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
try:
    from jarvis_core.config import MODEL_CATALOG_PATH
    CATALOG_PATH = str(MODEL_CATALOG_PATH)
except Exception:
    CATALOG_PATH = str(Path(__file__).resolve().parents[1] / "jarvis_data" / "model_catalog.json")

API_URL = "https://openrouter.ai/api/v1/models"

def fetch_models():
    """Fetch raw model data from OpenRouter."""
    print(f"[*] Fetching live model data from {API_URL}...")
    req = urllib.request.Request(API_URL, headers={"User-Agent": "JARVIS-Architect/1.0"})
    
    try:
        start_time = time.time()
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        print(f"[✓] Successfully retrieved {len(data['data'])} models in {time.time() - start_time:.2f}s.")
        return data['data']
    except Exception as e:
        print(f"[!] Critical Error fetching models: {e}")
        return []

def determine_category(model_id: str) -> str:
    """Categorize the model strictly by its vendor prefix or internal name."""
    mid = model_id.lower()
    if 'anthropic' in mid or 'claude' in mid:
        return 'Anthropic'
    elif 'openai' in mid or 'gpt' in mid or 'o1' in mid or 'o3' in mid:
        return 'OpenAI'
    elif 'google' in mid or 'gemini' in mid:
        return 'Google'
    elif 'deepseek' in mid:
        return 'DeepSeek'
    elif 'meta' in mid or 'llama' in mid:
        return 'Meta (Llama)'
    elif 'qwen' in mid:
        return 'Qwen'
    elif 'mistral' in mid:
        return 'Mistral'
    elif 'minimax' in mid:
        return 'MiniMax'
    elif 'cohere' in mid or 'command' in mid:
        return 'Cohere'
    else:
        return 'Wildcard_OS'

def process_catalog(raw_models):
    """Refine and sanitize the data for JARVIS ingestion."""
    processed = []
    
    for m in raw_models:
        # Some models might not have explicit pricing fields if they are routing variants
        pricing = m.get('pricing', {})
        prompt_cost = float(pricing.get('prompt', 0)) * 1_000_000
        completion_cost = float(pricing.get('completion', 0)) * 1_000_000
        
        # Determine capabilities
        arch = m.get('architecture', {})
        inputs = arch.get('input_modalities', ['text'])
        is_multimodal = 'image' in inputs or 'video' in inputs
        
        context_length = m.get('context_length', 0)
        
        entry = {
            "id": m.get('id'),
            "name": m.get('name'),
            "vendor": determine_category(m.get('id', '')),
            "context_length": context_length,
            "cost_input_1m": prompt_cost,
            "cost_output_1m": completion_cost,
            "is_multimodal": is_multimodal,
            "description": m.get('description', '')
        }
        processed.append(entry)
        
    return processed

def report_vanished(processed_models):
    """Stage 4.3.3: diff against whatever catalog is already on disk BEFORE the
    overwrite, and print any model id that existed before but doesn't now. Free
    OpenRouter models churn weekly; a silent overwrite hides that churn from the
    operator running this manually. Log-only -- this script stays a manual,
    human-run tool (no cron), so the fix is visibility, not automation. Runtime
    vanished-model handling (a model that 404s mid-session) is a SEPARATE,
    mechanical fix in brain/model_pool.py's failover walk, not this script."""
    if not os.path.exists(CATALOG_PATH):
        return  # first run ever -- nothing to diff against
    try:
        old = json.loads(Path(CATALOG_PATH).read_text(encoding="utf-8"))
        old_ids = {m.get("id") for m in old if m.get("id")}
    except Exception:
        return  # unreadable/corrupt prior catalog -- diffing it would be noise, not signal
    new_ids = {m.get("id") for m in processed_models if m.get("id")}
    vanished = sorted(old_ids - new_ids)
    if vanished:
        print(f"[!] {len(vanished)} model(s) vanished from the live catalog since last sync:")
        for mid in vanished:
            print(f"      - {mid}")


def write_catalog(processed_models):
    """Write the compressed data to the persistent cognitive store."""
    report_vanished(processed_models)
    os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)

    with open(CATALOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(processed_models, f, indent=2)

    print(f"[✓] Persisted stripped catalog to {CATALOG_PATH}")

if __name__ == "__main__":
    raw = fetch_models()
    if raw:
        cleaned = process_catalog(raw)
        write_catalog(cleaned)
        print("\n[SYSTEM] Local Model Catalog synchronization complete.")
