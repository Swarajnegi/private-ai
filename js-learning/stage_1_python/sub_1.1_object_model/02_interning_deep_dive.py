"""
interning_demo.py

JARVIS Learning Module: Understanding Python's Interning Behavior.

Run with:
    py -3.11 interning_demo.py

This script demonstrates:
    1. Which integers are interned (-5 to 256).
    2. Which strings are interned (identifier-like compile-time constants).
    3. Why you should NEVER rely on interning for correctness.
"""


def demo_integer_interning() -> None:
    print("=" * 60)
    print("INTEGER INTERNING (-5 to 256)")
    print("=" * 60)
    
    test_values = [-6, -5, 0, 100, 256, 257, 1000]
    
    for val in test_values:
        a = val
        b = val
        # Force Python to not optimize by using a function
        c = int(str(val))  # Dynamically create the integer
        
        is_same = a is c
        status = "✅ INTERNED" if is_same else "❌ NOT interned"
        print(f"  {val:>5}: a is c → {is_same!s:<5}  {status}")
    
    print()


def demo_string_interning() -> None:
    print("=" * 60)
    print("STRING INTERNING")
    print("=" * 60)
    
    # -------------------------------------------------------------------------
    # Case 1: Compile-time constant, identifier-like → INTERNED
    # -------------------------------------------------------------------------
    s1 = "hello"
    s2 = "hello"
    print(f"\n  Case 1: Compile-time, identifier-like")
    print(f"    s1 = 'hello'")
    print(f"    s2 = 'hello'")
    print(f"    s1 is s2 → {s1 is s2}  (✅ Interned)")
    
    # -------------------------------------------------------------------------
    # Case 2: Compile-time constant with underscore → INTERNED
    # -------------------------------------------------------------------------
    s3 = "doc_001"
    s4 = "doc_001"
    print(f"\n  Case 2: Compile-time with underscore")
    print(f"    s3 = 'doc_001'")
    print(f"    s4 = 'doc_001'")
    print(f"    s3 is s4 → {s3 is s4}  (✅ Interned - looks like identifier)")
    
    # -------------------------------------------------------------------------
    # Case 3: Compile-time constant with SPACE → NOT INTERNED
    # -------------------------------------------------------------------------
    s5 = "hello world"
    s6 = "hello world"
    print(f"\n  Case 3: Compile-time with space")
    print(f"    s5 = 'hello world'")
    print(f"    s6 = 'hello world'")
    result = s5 is s6
    # Note: CPython may still intern these in some cases due to peephole optimization
    print(f"    s5 is s6 → {result}  ({'✅ Interned (optimizer)' if result else '❌ NOT interned'})")
    
    # -------------------------------------------------------------------------
    # Case 4: Compile-time constant with HYPHEN → NOT INTERNED
    # -------------------------------------------------------------------------
    s7 = "doc-001"
    s8 = "doc-001"
    print(f"\n  Case 4: Compile-time with hyphen")
    print(f"    s7 = 'doc-001'")
    print(f"    s8 = 'doc-001'")
    result = s7 is s8
    print(f"    s7 is s8 → {result}  ({'✅ Interned (optimizer)' if result else '❌ NOT interned'})")
    
    # -------------------------------------------------------------------------
    # Case 5: Runtime-constructed (concatenation) → NOT INTERNED
    # -------------------------------------------------------------------------
    prefix = "doc"
    suffix = "_001"
    s9 = prefix + suffix  # Built at runtime
    s10 = "doc_001"       # Compile-time constant
    print(f"\n  Case 5: Runtime concatenation")
    print(f"    s9 = prefix + suffix  (runtime)")
    print(f"    s10 = 'doc_001'       (compile-time)")
    print(f"    s9 is s10 → {s9 is s10}  (❌ NOT interned - different objects)")
    print(f"    s9 == s10 → {s9 == s10}  (✅ Same VALUE)")
    
    # -------------------------------------------------------------------------
    # Case 6: F-string → NOT INTERNED
    # -------------------------------------------------------------------------
    n = 1
    s11 = f"doc_{n:03d}"  # f"doc_001" built at runtime
    s12 = "doc_001"
    print(f"\n  Case 6: F-string")
    print(f"    s11 = f'doc_{{n:03d}}'  (runtime, n=1)")
    print(f"    s12 = 'doc_001'")
    print(f"    s11 is s12 → {s11 is s12}  (❌ NOT interned)")
    print(f"    s11 == s12 → {s11 == s12}  (✅ Same VALUE)")
    
    print()


def demo_forced_interning() -> None:
    print("=" * 60)
    print("FORCING INTERNING WITH sys.intern()")
    print("=" * 60)
    
    import sys
    
    # Runtime-constructed strings are NOT interned by default
    prefix = "doc"
    suffix = "_001"
    s1 = prefix + suffix
    s2 = "doc_001"
    
    print(f"\n  Before intern():")
    print(f"    s1 = prefix + suffix  → id: {id(s1):#x}")
    print(f"    s2 = 'doc_001'        → id: {id(s2):#x}")
    print(f"    s1 is s2 → {s1 is s2}")
    
    # Force interning
    s1 = sys.intern(s1)
    s2 = sys.intern(s2)
    
    print(f"\n  After sys.intern():")
    print(f"    s1 = sys.intern(s1)   → id: {id(s1):#x}")
    print(f"    s2 = sys.intern(s2)   → id: {id(s2):#x}")
    print(f"    s1 is s2 → {s1 is s2}  (✅ Now the same object!)")
    
    print()


def demo_jarvis_implication() -> None:
    print("=" * 60)
    print("JARVIS IMPLICATION: Why This Matters")
    print("=" * 60)
    
    print("""
  In JARVIS, document IDs come from:
  
    1. User input           → "doc_001" (runtime string)
    2. Database queries     → f"doc_{row['id']}" (f-string)
    3. File paths           → path.stem (runtime string)
    4. Hardcoded constants  → "doc_001" (compile-time)
  
  If you use `is` to compare document IDs:
  
    user_id = input("Enter doc ID: ")  # "doc_001" typed by user
    stored_id = "doc_001"               # Compile-time constant
    
    if user_id is stored_id:  # ❌ WILL FAIL even if same text!
        return document
  
  RULE: Always use `==` for value comparison. Never rely on interning.
""")


if __name__ == "__main__":
    demo_integer_interning()
    demo_string_interning()
    demo_forced_interning()
    demo_jarvis_implication()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
  | Type    | Interned When...                          |
  |---------|-------------------------------------------|
  | Integer | Value is between -5 and 256 (inclusive)   |
  | String  | Compile-time constant AND identifier-like |
  
  GOLDEN RULE: Interning is an OPTIMIZATION, not a FEATURE.
               Never write code that DEPENDS on it.
               Always use `==` for value comparison.
""")
