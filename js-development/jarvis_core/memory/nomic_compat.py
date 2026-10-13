"""Nomic's encoder padding mask on Transformers 5. LAYER: Memory.

Nomic's remote encoder still calls a helper removed from ModuleUtilsMixin in
Transformers 5. Restore only its bidirectional encoder behavior on that model
instance. No global library patch, decoder support, or embedding-space change.
Reference: transformers v4.57.3 modeling_utils.py get_extended_attention_mask.
"""
from __future__ import annotations
from types import MethodType


def encoder_padding_mask(model, mask, input_shape, device=None, dtype=None):
    import torch
    if getattr(model.config, "is_decoder", False):
        raise ValueError("Nomic compatibility supports bidirectional encoders only")
    if mask.ndim == 2:
        expanded = mask.unsqueeze(1).unsqueeze(1)
    elif mask.ndim == 3:
        expanded = mask.unsqueeze(1)
    else:
        raise ValueError(f"unsupported Nomic attention mask shape: {tuple(mask.shape)}")
    target_dtype = dtype if dtype is not None else model.dtype
    expanded = expanded.to(dtype=target_dtype)
    return (expanded * -1 + 1) * torch.finfo(target_dtype).min


def ensure_nomic_mask(model) -> bool:
    if hasattr(model, "get_extended_attention_mask"):
        return False
    if type(model).__name__ != "NomicBertModel" or getattr(model.config, "is_decoder", False):
        raise TypeError("unexpected model for Nomic encoder compatibility")
    model.get_extended_attention_mask = MethodType(encoder_padding_mask, model)
    return True
