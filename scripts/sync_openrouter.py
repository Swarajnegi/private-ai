import urllib.request
import json
import os
import time

CATALOG_PATH = r"E:\J.A.R.V.I.S\jarvis_data\model_catalog.json"
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

def write_catalog(processed_models):
    """Write the compressed data to the persistent cognitive store."""
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
