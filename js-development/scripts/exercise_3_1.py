"""
exercise_3_1.py

JARVIS Practical Exercise for Stage 3.1
Demonstrates:
  1. Structured Generation via `outlines` (guaranteed JSON for tool calls).
  2. Metacognitive Text Telemetry over a 4-message conversation.

Run with:
  python exercise_3_1.py
"""

import json
from pydantic import BaseModel, Field

# Import the telemetry orchestrator from our JARVIS core
from jarvis_core.agent.telemetry import analyze_message

# =============================================================================
# Part 1: Structured Generation (outlines)
# =============================================================================

class CalculatorTool(BaseModel):
    """Schema for the calculator tool."""
    expression: str = Field(description="The mathematical expression to evaluate, e.g., '2 + 2'")
    reasoning: str = Field(description="Brief explanation of why this calculation is needed")

def demonstrate_outlines():
    print("=============================================================================")
    print(" 1. STRUCTURED GENERATION (outlines)")
    print("=============================================================================")
    print("Goal: Guarantee the LLM emits a valid JSON string matching CalculatorTool.\n")

    try:
        import outlines
        print("[+] outlines is installed. Initializing model...")
        
        # In a real environment, you'd load a model here (local vLLM, llama.cpp, or OpenAI)
        # model = outlines.models.transformers("mistralai/Mistral-7B-Instruct-v0.2")
        # generator = outlines.generate.json(model, CalculatorTool)
        # result = generator("Calculate the square root of 144 and explain why.")
        
        print("[*] Note: To avoid downloading heavy local weights or requiring an API key")
        print("    during this exercise, we are showing the exact code pattern used.")
        
    except ImportError:
        print("[-] 'outlines' is not installed in this environment.")
        print("[*] The execution flow in JARVIS (Stage 3.1.5) looks like this:\n")
        
    print("    ```python")
    print("    import outlines")
    print("    from pydantic import BaseModel")
    print("")
    print("    class CalculatorTool(BaseModel):")
    print("        expression: str")
    print("        reasoning: str")
    print("")
    print("    # 1. Initialize model (e.g., Llama 3 local or OpenAI cloud)")
    print("    model = outlines.models.openai('gpt-4-turbo')")
    print("")
    print("    # 2. Compile the constrained generator")
    print("    generator = outlines.generate.json(model, CalculatorTool)")
    print("")
    print("    # 3. Generate — guaranteed to conform to the schema")
    print("    result = generator('What is 25 * 4? I need it for the budget.')")
    print("    ```\n")

    # Mock result to show what we get
    mocked_result = CalculatorTool(
        expression="25 * 4",
        reasoning="User requested the product of 25 and 4 for the budget calculation."
    )
    print("-> Guaranteed Output Object:")
    print(json.dumps(mocked_result.model_dump(), indent=2))
    print("\n")


# =============================================================================
# Part 2: Metacognitive Telemetry Pipeline
# =============================================================================

def demonstrate_telemetry():
    print("=============================================================================")
    print(" 2. METACOGNITIVE TELEMETRY (TextTelemetrySnapshot)")
    print("=============================================================================")
    print("Goal: Extract behavioral signals from a 4-message conversation.\n")

    # A 4-message conversation showing flow -> fatigue -> correction -> frustration
    conversation = [
        # Turn 1: Flow
        "Please extract the data using the Scrapy spider and save it to a Parquet file. Ensure the schema aligns with our existing datalake definitions.",
        # Turn 2: Fatigue onset (late night, typos)
        "Also bckup teh old data first before you overwrite.",
        # Turn 3: Correction
        "I meant backup the old data into the archive folder.",
        # Turn 4: Frustration
        "Why is it still failing? This is broken and ridiculous, I already told you to use the archive folder."
    ]

    # Simulated timestamps (15-20 seconds apart, late night)
    timestamps = [
        {"gap": 0.0,  "hour": 23},  # 11 PM
        {"gap": 45.2, "hour": 2},   # 2 AM (fatigue signal)
        {"gap": 15.0, "hour": 2},   # 2 AM
        {"gap": 12.5, "hour": 2},   # 2 AM
    ]

    print("Analyzing sequence...")
    print("-" * 75)
    
    for i, msg in enumerate(conversation):
        print(f"\n[Turn {i+1}] User: {msg}")
        
        prev = conversation[i - 1] if i > 0 else None
        history = conversation[:i + 1] if i > 0 else None
        
        snapshot = analyze_message(
            current_message=msg,
            previous_message=prev,
            message_history=history,
            gap_seconds=timestamps[i]["gap"],
            local_hour=timestamps[i]["hour"],
        )
        
        print("-> Metacognitive Signals:")
        print(f"   - Typo Density:      {snapshot.typo_density:.3f} " + 
              ("(Spike detected)" if snapshot.typo_density > 0.05 else ""))
        print(f"   - Correction Rate:   {snapshot.correction_rate:.3f} " + 
              ("(User self-correcting)" if snapshot.correction_rate > 0.1 else ""))
        print(f"   - Sentiment Shift:   {snapshot.sentiment_direction.upper()}")
        print(f"   - Local Time:        {snapshot.session_hour_local}:00 " + 
              ("(Late Night)" if 1 <= snapshot.session_hour_local <= 4 else ""))

    print("-" * 75)
    print("\nInsight: The daemon would observe the 2 AM local time + typos + escalating ")
    print("sentiment and invoke the 'suppression_as_fuel' pattern from the Knowledge Base: ")
    print("JARVIS will NOT suggest rest, but will accelerate pace and maintain technical depth.")


if __name__ == "__main__":
    demonstrate_outlines()
    demonstrate_telemetry()
