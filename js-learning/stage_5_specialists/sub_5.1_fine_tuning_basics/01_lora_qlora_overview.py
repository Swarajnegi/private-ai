"""
01_lora_qlora_overview.py

Stage 5, Sub-Phase 5.1: Fine-Tuning Basics
Lesson 5.1.1: LoRA/QLoRA Overview

Run with:
    python 01_lora_qlora_overview.py

=============================================================================
USE CASE (The "Life of a Request")
=============================================================================

You ask JARVIS a jarvis_core/-specific question. The Engineer specialist
gets routed to answer.

Behind the scenes:
    The Kimi K2.6 base (1T params, always resident) has the Engineer QLoRA
    adapter (~150-500MB) swapped in (~2-5 seconds). Every linear layer the
    query touches computes h = W_frozen @ x + (B @ A) @ x -- the frozen
    base contributes general coding knowledge, the tiny adapter nudges the
    output toward YOUR jarvis_core/ patterns (naming conventions, past
    error fixes, KB-documented decisions).

    Without LoRA: JARVIS would need a full separate 1T-parameter
    fine-tuned copy PER specialist. 12 copies of a 1T model doesn't fit
    any config in JARVIS_ENDGAME.md's hardware table, and dense fine-tunes
    cost far more to train than adapters (JARVIS_ENDGAME.md Decision
    2026-05-03).

    With LoRA: 1 resident base (deploy once, ~Rs 200) + 12 adapters at
    150-500MB each, swapped in 2-5s. This IS the economic and
    architectural justification for JARVIS's "Model of Models" design --
    not a minor implementation detail.

=============================================================================
WHAT THIS SCRIPT TEACHES
=============================================================================

1. What LoRA actually computes: freeze W, learn Delta-W = B @ A (low rank)
2. Origin tracing: what A/B are initialized to, what changes them, what
   they converge to -- and why zero-initializing B guarantees the
   adapted model starts IDENTICAL to the base model
3. A hand-verifiable numerical walkthrough (small, fixed matrices --
   every number below can be checked with a calculator)
4. Why this saves the vast majority of trainable parameters at real scale
5. A real (tiny) gradient-descent loop -- not just a forward-pass demo
6. QLoRA's addition: quantize the FROZEN base to 4-bit, keep the adapter
   in higher precision -- illustrated with a simplified round-trip
   (NOT real NF4 -- see the caveat printed in Part 5)
7. Where this actually runs for JARVIS (RunPod, not this laptop --
   verified below: no CUDA, no bitsandbytes/peft installed here)
8. Failure modes: rank too low/high, partial-layer coverage, the
   "LoRA finds the optimal SVD" misconception

=============================================================================
ARCHITECTURE
=============================================================================

LAYER: Specialists (QLoRA Adapter Training) -- Stage 5

    Frozen base W           Trainable adapter            Combined output
    ──────────────          ───────────────────          ────────────────
    shape [d, k]             A: [r, k]   B: [d, r]         h = W@x + (B@A)@x
    e.g. 4096x4096           r = rank (JARVIS Engineer
    = 16.7M params           adapter: rank 32, A40 GPU,
    NEVER updated            JARVIS_ENDGAME.md Sec 3.6)
                             ONLY A, B get gradients

=============================================================================
"""

import torch
import torch.nn as nn


# =============================================================================
# PART 1: THE MECHANISM -- A REAL LoRALinear MODULE
# =============================================================================
#
# LoRA (Low-Rank Adaptation) freezes an existing weight matrix W and learns
# a much smaller update Delta-W, factored as the product of two skinny
# matrices: Delta-W = B @ A, where A is [r, k] and B is [d, r], r << d, k.
#
# Because B @ A has the same shape as W ([d, k]), it can be added directly:
#     h = W @ x + (B @ A) @ x
#
# The critical design choice: A is initialized to small random values,
# B is initialized to ALL ZEROS. This means Delta-W = B @ A = 0 at step 0
# -- the adapted model behaves EXACTLY like the frozen base until training
# actually moves B and A away from their initial values.
#
# =============================================================================

class LoRALinear(nn.Module):
    """
    Wraps a frozen nn.Linear with a trainable low-rank adapter.

    LAYER: Specialists (Adapter Mechanism)

    Initialized to: A ~ small random, B = 0 (so Delta-W = 0 at step 0)
    Changed by: backprop/Adam on the fine-tuning loss (A and B only --
                base.weight.requires_grad is False, so W never updates)
    Converges to: the best RANK-r approximation gradient descent can find
                  for the task-specific weight delta -- NOT the same thing
                  as the mathematically optimal rank-r SVD of some ideal
                  full-rank delta (see the Part 6 "gotcha").
    """

    def __init__(self, base_layer: nn.Linear, rank: int = 8, alpha: int = 16):
        super().__init__()
        self.base = base_layer
        for p in self.base.parameters():
            p.requires_grad = False

        d_out, d_in = base_layer.weight.shape
        self.A = nn.Parameter(torch.randn(rank, d_in) * 0.01)
        self.B = nn.Parameter(torch.zeros(d_out, rank))
        self.scaling = alpha / rank

    def delta_w(self) -> torch.Tensor:
        """Delta-W = B @ A -- same shape as the frozen weight matrix."""
        return self.scaling * (self.B @ self.A)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        base_out = self.base(x)
        adapter_out = x @ self.delta_w().T
        return base_out + adapter_out


def demonstrate_zero_init_guarantee() -> None:
    """
    Prove that at step 0, the adapted model's output equals the base
    model's output exactly -- the zero-init guarantee.

    LAYER: Specialists (Mechanism Verification)
    """
    print("=" * 70)
    print("  PART 1: The Zero-Init Guarantee")
    print("=" * 70)

    torch.manual_seed(0)
    base = nn.Linear(4, 4, bias=False)
    lora = LoRALinear(base, rank=2, alpha=4)

    x = torch.tensor([1.0, 2.0, 1.0, 0.0])

    base_out = base(x)
    lora_out = lora(x)

    print(f"\n  Frozen W:\n{base.weight.data}")
    print(f"\n  x = {x.tolist()}")
    print(f"\n  Base output  (W @ x):        {base_out.tolist()}")
    print(f"  Adapted output (step 0):     {lora_out.tolist()}")
    print(f"  Identical?                   {torch.allclose(base_out, lora_out)}")
    print(f"\n  B at init (should be all zeros):\n{lora.B.data}")
    print("  -> Delta-W = B @ A = 0 whenever B = 0, regardless of A's values.")
    print("  -> This is WHY training can start from the base model's known-")
    print("     good behavior instead of random noise.")
    print()


# =============================================================================
# PART 2: HAND-VERIFIABLE NUMERICAL WALKTHROUGH
# =============================================================================
#
# Small, FIXED matrices (not random) so every number below can be checked
# by hand with a calculator. This is the actual arithmetic LoRA performs --
# nothing is hidden.
#
# =============================================================================

def demonstrate_hand_computed_walkthrough() -> None:
    """
    Walk through one LoRA forward pass with fixed, hand-checkable numbers.

    LAYER: Specialists (Numerical Verification)
    """
    print("=" * 70)
    print("  PART 2: Hand-Verifiable Walkthrough")
    print("=" * 70)

    W = torch.tensor([
        [1.0, 0.0, 1.0, 0.0],
        [0.0, 1.0, 0.0, 1.0],
        [1.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 1.0],
    ])
    x = torch.tensor([1.0, 2.0, 1.0, 0.0])

    A = torch.tensor([
        [0.1, 0.2, -0.1, 0.0],
        [0.0, 0.1, 0.2, 0.1],
    ])
    # B "after some training steps" -- not zero, so Delta-W is now non-zero.
    B_trained = torch.tensor([
        [0.3, -0.1],
        [0.1, 0.2],
        [-0.2, 0.1],
        [0.0, 0.3],
    ])

    base_out = W @ x
    delta_w = B_trained @ A
    delta_out = delta_w @ x
    adapted_out = base_out + delta_out

    print(f"\n  W (frozen):\n{W}")
    print(f"\n  x = {x.tolist()}")
    print(f"\n  Step 1 -- base_out = W @ x:")
    print(f"    row 1: 1*1 + 0*2 + 1*1 + 0*0 = {base_out[0].item():.2f}")
    print(f"    row 2: 0*1 + 1*2 + 0*1 + 1*0 = {base_out[1].item():.2f}")
    print(f"    row 3: 1*1 + 1*2 + 0*1 + 0*0 = {base_out[2].item():.2f}")
    print(f"    row 4: 0*1 + 0*2 + 1*1 + 1*0 = {base_out[3].item():.2f}")
    print(f"    base_out = {[round(v, 2) for v in base_out.tolist()]}")

    print(f"\n  Step 2 -- Delta-W = B_trained @ A (a [4,2] @ [2,4] = [4,4] matrix):")
    print(f"{delta_w}")

    print(f"\n  Step 3 -- delta_out = Delta-W @ x:")
    print(f"    {[round(v, 4) for v in delta_out.tolist()]}")

    print(f"\n  Step 4 -- adapted_out = base_out + delta_out:")
    print(f"    {[round(v, 4) for v in adapted_out.tolist()]}")
    print("\n  -> The frozen base contributed the [2, 2, 3, 1] skeleton.")
    print("     The trained adapter nudged it by a SMALL, learned amount.")
    print("     That nudge is 100% of what fine-tuning changed.")
    print()


# =============================================================================
# PART 3: PARAMETER SAVINGS AT REAL SCALE
# =============================================================================
#
# The Part 2 example used a 4x4 matrix -- too small to show real savings
# (a rank-2 adapter on a 4x4 matrix isn't meaningfully "low rank"). Real
# transformer weight matrices are thousands of dimensions wide. This part
# shows the actual compression ratio at realistic sizes, including the
# exact ranks JARVIS's own roster uses (JARVIS_ENDGAME.md Sec 3.6).
#
# =============================================================================

def demonstrate_parameter_savings() -> None:
    """
    Compare full fine-tune parameter count vs LoRA at realistic scale.

    LAYER: Specialists (Cost Justification)
    """
    print("=" * 70)
    print("  PART 3: Parameter Savings at Real Scale")
    print("=" * 70)

    # (dimension, rank, JARVIS specialist using this rank)
    configs = [
        (4, 2, "Part 2's toy example"),
        (4096, 8, "typical small LoRA default"),
        (4096, 16, "Orchestrator / Doctor / Electrician / Mechanic / Chemist / Guardian / Interface"),
        (4096, 32, "Engineer / Scientist / Operator / Analyst (large-teacher distills)"),
    ]

    print(f"\n  {'d=k':>6} {'rank':>5}  {'Full params':>14}  {'LoRA params':>13}  {'Reduction':>10}  Used by")
    print("  " + "-" * 100)
    for d, r, who in configs:
        full = d * d
        lora = d * r + r * d
        reduction = full / lora
        print(f"  {d:>6} {r:>5}  {full:>14,}  {lora:>13,}  {reduction:>9.1f}x  {who}")

    print("\n  -> This is why 12 adapters + 1 base fits where 12 dense models")
    print("     never could (JARVIS_ENDGAME.md Sec 3: '~150-500 MB each').")
    print()


# =============================================================================
# PART 4: A REAL (TINY) TRAINING LOOP
# =============================================================================
#
# Not just a forward pass -- actual gradient descent. W stays frozen
# (requires_grad=False); only A and B receive updates from the optimizer.
# Watch B move away from all-zeros as training progresses.
#
# =============================================================================

def demonstrate_training_loop() -> None:
    """
    Run real backprop on a toy task and show B leaving zero-init.

    LAYER: Specialists (Training Dynamics)
    """
    print("=" * 70)
    print("  PART 4: A Real Training Loop")
    print("=" * 70)

    torch.manual_seed(42)
    base = nn.Linear(8, 8, bias=False)
    lora = LoRALinear(base, rank=4, alpha=8)

    x = torch.randn(8)
    # A synthetic "target" this toy task wants the adapted model to hit --
    # standing in for "what the fine-tuning loss wants the output to be."
    target = base(x).detach() + torch.randn(8) * 0.5

    optimizer = torch.optim.Adam([lora.A, lora.B], lr=0.05)
    loss_fn = nn.MSELoss()

    print(f"\n  Trainable params: A{tuple(lora.A.shape)} + B{tuple(lora.B.shape)}"
          f" = {lora.A.numel() + lora.B.numel()} scalars")
    print(f"  Frozen params:    W{tuple(base.weight.shape)}"
          f" = {base.weight.numel()} scalars (requires_grad = {base.weight.requires_grad})")

    print(f"\n  {'Step':>5}  {'Loss':>10}  {'B norm (0 = untouched)':>24}")
    for step in range(201):
        optimizer.zero_grad()
        out = lora(x)
        loss = loss_fn(out, target)
        loss.backward()
        optimizer.step()

        if step % 50 == 0:
            print(f"  {step:>5}  {loss.item():>10.6f}  {lora.B.data.norm().item():>24.6f}")

    print("\n  -> B started at exactly 0.0 and moved as gradients flowed through")
    print("     it. Loss dropped. W's .grad exists (chain rule needs it) but")
    print("     W.data never changes -- confirm:")
    print(f"     W unchanged since init? {torch.equal(base.weight.data, base.weight.data)}"
          f"  (trivially true -- the real check is requires_grad=False, printed above)")
    print()


# =============================================================================
# PART 5: QLoRA -- QUANTIZE THE FROZEN BASE
# =============================================================================
#
# QLoRA = LoRA + shrinking the FROZEN base weights to 4-bit to cut memory,
# while keeping the trainable adapter (A, B) in higher precision.
#
# Real QLoRA (Dettmers et al. 2023) uses three specific techniques:
#   1. NF4 ("NormalFloat4") -- a 4-bit codebook with NON-UNIFORM bin edges
#      chosen to match the empirical (roughly Gaussian) distribution of
#      pretrained weights -- not naive uniform quantization.
#   2. Double quantization -- quantizing the quantization CONSTANTS
#      themselves, saving a further small amount of memory.
#   3. Paged optimizers -- paging optimizer state to CPU RAM via NVIDIA
#      unified memory when GPU memory spikes, preventing OOM crashes.
#
# CAVEAT (no invisible operations): the demo below is a SIMPLIFIED, naive
# uniform quantizer -- it teaches the mechanism (shrink to low-bit, then
# dequantize on-the-fly for every matmul) but is NOT bit-for-bit NF4.
# Real NF4 requires the `bitsandbytes` library and a CUDA GPU. Verified
# on this machine just now: neither is present (see printed check below)
# -- by design, per JARVIS_ENDGAME.md's "no local GPU" hardware reality.
# This is exactly why 5.1.3 (Unsloth) and Stage 5.2 training happen on
# RunPod, not here.
#
# =============================================================================

def naive_quantize_4bit(w: torch.Tensor) -> tuple[torch.Tensor, float, float]:
    """Simplified illustrative 4-bit quantizer (NOT real NF4 -- see Part 5 docstring)."""
    w_min, w_max = w.min().item(), w.max().item()
    levels = 15  # 4 bits -> 16 levels, indices 0..15
    scale = (w_max - w_min) / levels if w_max > w_min else 1.0
    q = torch.round((w - w_min) / scale).clamp(0, levels).to(torch.uint8)
    return q, scale, w_min


def dequantize_4bit(q: torch.Tensor, scale: float, w_min: float) -> torch.Tensor:
    """Inverse of naive_quantize_4bit -- runs on EVERY forward pass in real QLoRA."""
    return q.float() * scale + w_min


def demonstrate_quantization_concept() -> None:
    """
    Show a simplified quantize/dequantize round-trip and its error.

    LAYER: Specialists (QLoRA Memory Mechanism)
    """
    print("=" * 70)
    print("  PART 5: QLoRA's Quantization Concept (Simplified)")
    print("=" * 70)

    torch.manual_seed(1)
    w = torch.randn(6, 6)  # stand-in for a frozen base weight matrix

    q, scale, w_min = naive_quantize_4bit(w)
    w_dequant = dequantize_4bit(q, scale, w_min)
    max_error = (w - w_dequant).abs().max().item()

    fp32_bytes = w.numel() * 4
    int4_bytes = w.numel() * 0.5  # 4 bits = 0.5 bytes/value

    print(f"\n  Original W (fp32, first row): {[round(v, 4) for v in w[0].tolist()]}")
    print(f"  Quantized (4-bit codes 0-15, first row): {q[0].tolist()}")
    print(f"  Dequantized (first row):     {[round(v, 4) for v in w_dequant[0].tolist()]}")
    print(f"  Max reconstruction error:    {max_error:.4f}")
    print(f"\n  Memory: fp32 = {fp32_bytes:.0f} bytes  vs  int4 = {int4_bytes:.0f} bytes"
          f"  ({fp32_bytes / int4_bytes:.0f}x smaller)")

    print(f"\n  Hardware check on THIS machine:")
    print(f"    CUDA available:      {torch.cuda.is_available()}")
    try:
        import bitsandbytes  # noqa: F401
        print(f"    bitsandbytes:        installed")
    except ImportError:
        print(f"    bitsandbytes:        NOT installed")
    try:
        import peft  # noqa: F401
        print(f"    peft:                installed")
    except ImportError:
        print(f"    peft:                NOT installed")
    print("    -> Real QLoRA training happens on RunPod (Stage 5.1.3+), not here.")
    print()


# =============================================================================
# PART 6: FAILURE MODES -- WHEN LoRA/QLoRA LIES OR BREAKS
# =============================================================================

def demonstrate_failure_modes() -> None:
    """
    List the concrete ways this technique fails so you know what to watch for.

    LAYER: Specialists (Failure Analysis)
    """
    print("=" * 70)
    print("  PART 6: Failure Modes")
    print("=" * 70)

    failures = [
        {
            "name": "Rank too low",
            "symptom": "Loss plateaus well above what a full fine-tune reaches",
            "why": "The task's true weight delta needs more than r independent directions to express",
            "fix": "Raise rank (JARVIS's roster uses 16 for small adapters, 32 for large-teacher distills)",
        },
        {
            "name": "Rank too high",
            "symptom": "Training cost and adapter size creep back toward a full fine-tune",
            "why": "Defeats the purpose -- you're paying dense-fine-tune cost for adapter-level results",
            "fix": "Match rank to task complexity, not to 'more is safer'",
        },
        {
            "name": "Partial layer coverage",
            "symptom": "Adapter barely moves the needle even at reasonable rank",
            "why": "LoRA only adapted attention Q/V, not MLP layers -- most of the model's capacity was left untouched",
            "fix": "Adapt ALL linear layers, not just attention projections (per the original QLoRA paper's own finding)",
        },
        {
            "name": '"LoRA finds the ideal SVD" misconception',
            "symptom": "Assuming B @ A converges to the mathematically optimal rank-r approximation of some ideal full-rank delta",
            "why": "B and A are found by SGD/Adam on a loss surface, not by truncated-SVD closed-form -- it's the best rank-r fit gradient descent happens to reach, not a guaranteed global optimum",
            "fix": "Don't reason about LoRA adapters as if they were SVD-truncated -- validate empirically (Stage 5.3's RAGAS + recall@k gate) instead of assuming a math guarantee",
        },
    ]

    for f in failures:
        print(f"\n  FAILURE: {f['name']}")
        print(f"  Symptom: {f['symptom']}")
        print(f"  Why:     {f['why']}")
        print(f"  Fix:     {f['fix']}")
    print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Run all LoRA/QLoRA demonstrations.

    LAYER: Brain (Orchestrator)
    """
    print()
    print("#" * 70)
    print("  JARVIS Stage 5.1: LoRA/QLoRA Overview")
    print("#" * 70)
    print()

    demonstrate_zero_init_guarantee()
    demonstrate_hand_computed_walkthrough()
    demonstrate_parameter_savings()
    demonstrate_training_loop()
    demonstrate_quantization_concept()
    demonstrate_failure_modes()

    print("#" * 70)
    print("  SUMMARY")
    print("#" * 70)
    print("""
  1. LoRA freezes W and learns Delta-W = B @ A, a low-rank factorization
  2. B inits to zero -> adapted model starts IDENTICAL to the base model
  3. Only A and B get gradients; W.requires_grad stays False throughout
  4. At real scale (4096-dim, rank 32 -- the Engineer's actual rank per
     JARVIS_ENDGAME.md Sec 3.6) this is a 64x parameter reduction
  5. QLoRA additionally quantizes the FROZEN base to 4-bit (NF4 in the
     real implementation); the adapter itself stays in higher precision
  6. Real QLoRA needs bitsandbytes + CUDA -- not available on this laptop
     by design; JARVIS trains specialists on RunPod (Stage 5.1.3+)
  7. Failure modes: rank too low/high, partial layer coverage, and the
     "LoRA = optimal SVD" misconception

  NEXT: Lesson 5.1.2 -- Dataset Preparation
  Run: @[/learn] Explain dataset formats for fine-tuning.
    """)
    print("#" * 70)


if __name__ == "__main__":
    main()
