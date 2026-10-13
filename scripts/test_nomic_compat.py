"""Hermetic Nomic compatibility checks; no model loading. LAYER: Tools."""
from __future__ import annotations
import argparse
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"js-development"))
import torch
from jarvis_core.memory.nomic_compat import ensure_nomic_mask, encoder_padding_mask


class MaskTests(unittest.TestCase):
    def test_encoder_mask_padding_shapes_and_dtypes(self):
        for dtype in (torch.float32,torch.float16,torch.bfloat16):
            model=SimpleNamespace(config=SimpleNamespace(is_decoder=False),dtype=dtype)
            mask=torch.tensor([[1,1,0],[1,0,0]])
            result=encoder_padding_mask(model,mask,(2,3))
            self.assertEqual(tuple(result.shape),(2,1,1,3))
            self.assertEqual(result.dtype,dtype)
            self.assertEqual(result[0,0,0,0].item(),0)
            self.assertEqual(result[0,0,0,2].item(),torch.finfo(dtype).min)
            self.assertEqual(tuple(encoder_padding_mask(model,mask[:,None,:],(2,3)).shape),(2,1,1,3))

    def test_existing_method_and_model_restrictions(self):
        model=SimpleNamespace(get_extended_attention_mask=lambda:None)
        original=model.get_extended_attention_mask
        self.assertFalse(ensure_nomic_mask(model));self.assertIs(original,model.get_extended_attention_mask)
        with self.assertRaises(TypeError): ensure_nomic_mask(SimpleNamespace())
        model=SimpleNamespace(config=SimpleNamespace(is_decoder=True),dtype=torch.float32)
        with self.assertRaises(ValueError): encoder_padding_mask(model,torch.ones(1,3),(1,3))
        model.config.is_decoder=False
        with self.assertRaises(ValueError): encoder_padding_mask(model,torch.ones(3),(3,))

    def test_binding_is_instance_local(self):
        cls=type("NomicBertModel",(),{})
        first,second=cls(),cls()
        first.config=second.config=SimpleNamespace(is_decoder=False)
        first.dtype=second.dtype=torch.float32
        self.assertTrue(ensure_nomic_mask(first))
        self.assertFalse(hasattr(second,"get_extended_attention_mask"))
        self.assertEqual(first.get_extended_attention_mask(torch.ones(1,3),(1,3)).sum().item(),0)


def main():
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true");p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MaskTests))
    return 0 if result.wasSuccessful() else 1
if __name__=="__main__": raise SystemExit(main())
