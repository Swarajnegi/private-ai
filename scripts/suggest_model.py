import argparse
import json
import math
import os

CATALOG_PATH = r"E:\J.A.R.V.I.S\jarvis_data\model_catalog.json"

def load_catalog():
    if not os.path.exists(CATALOG_PATH):
        print("Error: Catalog not found. Please run scripts/sync_openrouter.py first.")
        return []
    with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_args():
    parser = argparse.ArgumentParser(description="JARVIS Dynamic Model Suggester")
    parser.add_argument("--task", type=str, default="general", choices=["coding", "reasoning", "general", "vision"], help="Primary task constraint")
    parser.add_argument("--max_cost_input", type=float, default=10.0, help="Max $ cost per 1M input tokens")
    parser.add_argument("--max_cost_output", type=float, default=30.0, help="Max $ cost per 1M output tokens")
    parser.add_argument("--min_context", type=int, default=8000, help="Minimum required context window")
    parser.add_argument("--top_k", type=int, default=3, help="Number of results to return")
    return parser.parse_args()

def evaluate_model(model, args):
    """
    Given a model dictionary, determine if it passes strict hard filters.
    If it passes, return a float score (lower is better, representing 'cost-efficiency penalty').
    We adjust the 'cost' score heuristically based on the task type to favor better architectures.
    """
    
    # 1. HARD FILTERS (If it fails these, score is Infinity = rejected)
    if model['cost_input_1m'] > args.max_cost_input: return float('inf')
    if model['cost_output_1m'] > args.max_cost_output: return float('inf')
    if model['context_length'] < args.min_context: return float('inf')
    if args.task == "vision" and not model.get('is_multimodal', False): return float('inf')
    
    # Ignore broken or unpriced models gracefully
    if model['cost_input_1m'] <= 0 and model['cost_output_1m'] <= 0: return float('inf')
    if "free" in model['id'].lower() and args.task in ["coding", "reasoning"]: 
        pass # Free models are okay, but usually terrible for deep logic. We won't block them, but they get no boosts.
        
    # 2. BASE SCORE
    # Instead of purely prioritizing the cheapest model on OpenRouter (which suggests tiny 3B models), 
    # we set a baseline score of 10.0, and subtract based on capability, while adding a slight penalty for cost.
    score = 10.0 + (model['cost_input_1m'] * 2) + model['cost_output_1m']
    
    # 3. HEURISTIC BOOSTS (Subtract score to make it 'better' internally so it floats to the top)
    name_str = model['name'].lower()
    id_str = model['id'].lower()
    vendor = model.get('vendor', '')
    
    # Global Elite Tier Boosts
    if "claude-3.7-sonnet" in id_str or "claude-3.5-sonnet" in id_str: score -= 7.0
    if "deepseek/deepseek-chat" in id_str: score -= 6.0
    if "gemini-2.5-flash" in id_str: score -= 6.0
    if "o3-mini" in id_str: score -= 5.0
    if "minimax-01" in id_str: score -= 4.0
    if "qwen-2.5-coder-32b" in id_str: score -= 4.0
    if "llama-3.1-405b" in id_str: score -= 4.0
    
    # Task specific bumps
    if args.task == "coding":
        if "coder" in name_str or "coder" in id_str: score -= 2.0
    
    elif args.task == "reasoning":
        if "o1" in id_str or "o3" in id_str: score -= 3.0
        if "r1" in id_str: score -= 3.0
        if "opus" in name_str: score -= 2.0
        
    # If the user asks for a massive context length, strongly favor Gemini
    if args.min_context >= 200000:
        if "gemini" in vendor: score -= 4.0
        
    return score

if __name__ == "__main__":
    args = parse_args()
    catalog = load_catalog()
    
    if not catalog:
        exit(1)
        
    # Score all models
    scored_models = []
    for m in catalog:
        score = evaluate_model(m, args)
        if score != float('inf'):
            scored_models.append((score, m))
            
    # Sort by score ascending (lowest penalized cost first)
    scored_models.sort(key=lambda x: x[0])
    
    top_k = scored_models[:args.top_k]
    
    print(f"=== JARVIS MODEL ROUTING RECOMMENDATIONS ===")
    print(f"Task: {args.task.upper()} | Min Context: {args.min_context} | Max In: ${args.max_cost_input:.2f} | Max Out: ${args.max_cost_output:.2f}\n")
    
    if not top_k:
        print("[!] No models found matching these constraints.")
        exit(1)
        
    for idx, (score, m) in enumerate(top_k):
        cost_in = f"${m['cost_input_1m']:.3f}"
        cost_out = f"${m['cost_output_1m']:.3f}"
        ctx = f"{m['context_length']//1000}k"
        
        print(f"[{idx+1}] {m['name']} (Vendor: {m['vendor']})")
        print(f"    API Slug: {m['id']}")
        print(f"    Context: {ctx} | Cost: {cost_in} in / {cost_out} out")
        print(f"    Internal Score: {score:.3f}\n")
