"""
bash_classifier.py

JARVIS Agent Layer (Classifier): Bash AST safe-command classifier.

Import with:
    from jarvis_core.agent.bash_classifier import BashClassifier, SAFE_COMMANDS

LAYER: Agent (Classifier)

=============================================================================
THE BIG PICTURE
=============================================================================

Without an AST-aware Bash classifier:
    -> Every shell-tool invocation hits the permission UX. The user is
       prompted for `grep -n foo bar.txt` just as loudly as for
       `rm -rf /tmp`. Permission fatigue kicks in; the user starts
       click-allowing everything to escape the friction. Safety collapses.
    -> A naive substring check (e.g., "if 'rm' in cmd: deny") gets fooled
       by `echo "ham" | grep ham` (matches "rm"), and at the same time
       MISSES the OpenClaude CVE pattern: command substitution embedded
       inside an array subscript -- `echo "${arr[$(rm -rf /)]}"` -- because
       the dangerous token is hidden inside a `$()` that the eye skips.

With this classifier (STEAL #10, port of OpenClaude bashPermissions.ts):
    -> The command is parsed into a bashlex AST. Every command node's first
       word (the executable name) is checked against a whitelist of
       read-only utilities (grep, cat, ls, head, tail, wc, find, etc.).
    -> Per-command unsafe-flag denylists block the dangerous edge cases:
       `sed -i` (inplace), `awk -i` (inplace), `find -delete / -exec`.
    -> A regex pre-check rejects the OpenClaude CVE: command-substitution
       inside an array-subscript (OpenClaude commit 4a98a4a). This pattern
       can survive bashlex parsing in older versions and must be denied
       structurally.
    -> Result: routine read-only ops are auto-ALLOWed, dangerous ops are
       structurally DENIed, everything else falls through to ASK (the
       permission engine then handles user prompt / rule matching).

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: shell_run tool emits {"command": "grep -n foo bar.txt"}.
        The permission engine looks up the registered classifier for
        "shell_run" and calls classifier.classify_async(tool_input).
        |
        v
STEP 2: classify(command) runs:
            a. Empty/whitespace -> ASK (let permission engine handle)
            b. _ARRAY_SUBSCRIPT_CMDSUB regex search -> DENY structurally
               (the OpenClaude CVE pattern can never be safe)
            c. If bashlex missing -> ASK (soft-fail conservatively)
            d. bashlex.parse() -> walk the AST recursively
            e. For each command node: if name not in SAFE_COMMANDS -> ASK
               If name in UNSAFE_FLAGS and any arg matches -> DENY
            f. All commands cleared -> ALLOW
        |
        v
STEP 3: Permission engine receives ALLOW / ASK / DENY:
            ALLOW -> tool fires, no prompt
            DENY  -> tool blocked, no prompt
            ASK   -> fallback rule matching, then user prompt if needed

=============================================================================

Conservative posture: when ANY uncertainty arises (parser error, unknown
command, bashlex unavailable), the classifier returns ASK. It never
auto-ALLOWs in the absence of evidence. The only proactive answer it gives
is DENY for structural CVEs and unsafe flags on otherwise-safe commands.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterable, Optional

try:
    from jarvis_core.agent.permissions import PermissionDecision
except ImportError:
    from enum import Enum

    class PermissionDecision(str, Enum):
        ALLOW = "allow"
        ASK = "ask"
        DENY = "deny"

try:
    import bashlex
    _BASHLEX_AVAILABLE = True
except ImportError:
    bashlex = None
    _BASHLEX_AVAILABLE = False


# =============================================================================
# Part 1: SAFE-COMMAND WHITELIST + PER-COMMAND UNSAFE-FLAG DENYLIST
# =============================================================================

# awk and sed deliberately EXCLUDED from SAFE_COMMANDS even though they
# look like read-only filters: awk has system()/getline/pipe-to-shell, and
# GNU sed has the 'e' command + 'W'/'R' file ops. Both are Turing-complete
# scripting languages whose program text is a positional arg -- no flag
# denylist catches arbitrary `awk 'BEGIN{system("rm -rf /")}'`. Punt to ASK.
SAFE_COMMANDS: FrozenSet[str] = frozenset({
    "grep", "egrep", "fgrep", "cat", "ls", "head", "tail", "wc",
    "find", "echo", "pwd", "which", "stat", "file", "test", "true",
    "false", "basename", "dirname", "tr", "sort", "uniq", "cut",
    "date", "printf", "yes", "expr",
})

# Per-command unsafe-flag patterns. Each entry is a list of regex patterns
# (compiled at module load) that match a flag in any of its known forms.
# Matching is done with re.fullmatch against each argument.
# find: writing-primaries `-fprint*`, `-fls`, plus exec primaries.
# Note: combined short flags (e.g. -ni for sed) and long flags
# (--in-place=.bak) are handled by the regex set below.
_UNSAFE_FLAG_PATTERNS: Dict[str, list] = {
    "find": [
        re.compile(r"^-delete$"),
        re.compile(r"^-exec(?:dir)?$"),
        re.compile(r"^-ok(?:dir)?$"),
        re.compile(r"^-fprint(?:f|0)?$"),
        re.compile(r"^-fls$"),
    ],
}


# =============================================================================
# Part 2: STRUCTURAL CVE REGEX (OpenClaude fix 4a98a4a)
# =============================================================================

# Matches command substitution inside an array subscript:
#     ${var[$( ... )]}  ${arr[ $(rm -rf /) ]}  ${m[a$(x)b]}
# The regex tolerates arbitrary characters (incl. whitespace) between `[`
# and `$(` so an attacker can't bypass via `${arr[ $(...)]}` insertion.
# Some bashlex versions evaluate the cmdsub during AST construction or
# fail to surface the inner command node -- this pre-check catches it
# structurally before parsing.
_ARRAY_SUBSCRIPT_CMDSUB = re.compile(r"\$\{[^{}]*\[[^\]{}]*\$\(")

# Set of bashlex redirect operators that WRITE to a file (or network FD).
# Read-only redirects (`<`) are allowed because the destination is the
# caller's existing file (the permission engine still gates the outer
# operation). Process substitutions are handled separately.
_WRITE_REDIRECT_OPS: FrozenSet[str] = frozenset({
    ">", ">>", ">|", "&>", "&>>", ">&", "1>", "2>", "1>>", "2>>", "1>|",
    "2>|", "&>|",
})


# =============================================================================
# Part 3: BASH CLASSIFIER
# =============================================================================

class BashClassifier:
    """Classify a bash command for the permission engine.

    Returns ALLOW for known read-only operations, DENY for structural
    CVEs and unsafe-flag combinations, ASK for everything else.
    """

    def __init__(self, extra_safe_commands: Iterable[str] = ()) -> None:
        self._safe: FrozenSet[str] = SAFE_COMMANDS | frozenset(extra_safe_commands)

    def classify(self, command: str) -> PermissionDecision:
        """Synchronous classification of a single bash command string."""
        if not command.strip():
            return PermissionDecision.ASK

        if _ARRAY_SUBSCRIPT_CMDSUB.search(command):
            return PermissionDecision.DENY

        if not _BASHLEX_AVAILABLE:
            return PermissionDecision.ASK

        try:
            parts = bashlex.parse(command)
        except Exception:
            return PermissionDecision.ASK

        nodes: list = []
        for part in parts:
            _collect_command_nodes(part, nodes)

        if not nodes:
            return PermissionDecision.ASK

        for node in nodes:
            # Detect write-direction redirects on this command node. Any
            # redirect that writes to a file/FD downgrades to ASK so the
            # permission engine prompts the user (the target path can't be
            # validated structurally here).
            if _has_write_redirect(node):
                return PermissionDecision.ASK

            name, args = _extract_name_and_args(node)
            if name is None:
                return PermissionDecision.ASK
            if name not in self._safe:
                return PermissionDecision.ASK

            # Match unsafe flags by regex against each argument (handles
            # combined short flags, long flags with =, and suffix variants
            # like -i.bak).
            patterns = _UNSAFE_FLAG_PATTERNS.get(name)
            if patterns:
                for a in args:
                    if any(p.fullmatch(a) for p in patterns):
                        return PermissionDecision.DENY

        return PermissionDecision.ALLOW

    async def classify_async(
        self, tool_input: Dict[str, Any]
    ) -> Optional[PermissionDecision]:
        """Async entry point for PermissionContext.register_classifier."""
        command = tool_input.get("command", "")
        if not command:
            return None
        return self.classify(command)


# =============================================================================
# Part 4: AST WALKING HELPERS
# =============================================================================

def _collect_command_nodes(node: Any, sink: list) -> None:
    """Recursively walk a bashlex AST and append every CommandNode to sink.

    bashlex node kinds we care about:
        - 'command'      -- terminal: has .parts = [word, word, ...]
        - 'list'         -- A; B; C
        - 'pipeline'     -- A | B
        - 'compound'     -- subshells, groupings
        - 'commandsubstitution' -- $(...), `...`
        - 'processsubstitution' -- <(...) >(...)
        - 'if', 'for', 'while', 'function' -- compound bodies
    Anything inside any of these nodes still spawns commands; walk every
    sub-attribute that holds child nodes.
    """
    kind = getattr(node, "kind", None)
    if kind == "command":
        sink.append(node)

    for attr in ("parts", "list", "command", "body", "condition", "then",
                 "else", "elifs"):
        child = getattr(node, attr, None)
        if child is None:
            continue
        if isinstance(child, list):
            for sub in child:
                _collect_command_nodes(sub, sink)
        else:
            _collect_command_nodes(child, sink)


def _extract_name_and_args(command_node: Any) -> tuple:
    """From a bashlex 'command' node, return (executable_name, [args])."""
    parts = getattr(command_node, "parts", None) or []
    words: list = []
    for p in parts:
        if getattr(p, "kind", None) == "word":
            w = getattr(p, "word", None)
            if w is not None:
                words.append(w)
    if not words:
        return None, []
    return words[0], words[1:]


def _has_write_redirect(command_node: Any) -> bool:
    """True if this command node carries a redirect that WRITES to a file/FD.

    bashlex represents redirects as parts with kind='redirect' carrying a
    .type attribute that is the operator string ('>', '>>', '2>', etc.).
    """
    parts = getattr(command_node, "parts", None) or []
    for p in parts:
        if getattr(p, "kind", None) != "redirect":
            continue
        op = getattr(p, "type", None) or getattr(p, "redirect", None)
        if op in _WRITE_REDIRECT_OPS:
            return True
    return False


# =============================================================================
# MAIN ENTRY POINT (Smoke tests inline; run as a script)
# =============================================================================

if __name__ == "__main__":
    from typing import List
    import asyncio

    print("=" * 60)
    print("  BashClassifier -- Smoke Test")
    print("=" * 60)
    print(f"  bashlex available: {_BASHLEX_AVAILABLE}")

    classifier = BashClassifier()

    _counter = [0]
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        if cond:
            _counter[0] += 1
        else:
            failed.append("FAIL: " + name + ((" (" + hint + ")") if hint else ""))

    # ---- T1: safe grep ---------------------------------------------------
    r1 = classifier.classify("grep -n foo bar.txt")
    check("T1 grep -n foo bar.txt -> ALLOW",
          r1 == PermissionDecision.ALLOW, str(r1))

    # ---- T2: safe ls -----------------------------------------------------
    r2 = classifier.classify("ls -la /tmp")
    check("T2 ls -la /tmp -> ALLOW",
          r2 == PermissionDecision.ALLOW, str(r2))

    # ---- T3: safe echo ---------------------------------------------------
    r3 = classifier.classify("echo hello")
    check("T3 echo hello -> ALLOW",
          r3 == PermissionDecision.ALLOW, str(r3))

    # ---- T4: cat read-only (outer perms still apply) ---------------------
    r4 = classifier.classify("cat /etc/passwd")
    check("T4 cat /etc/passwd -> ALLOW",
          r4 == PermissionDecision.ALLOW, str(r4))

    # ---- T5: rm is NOT safe ----------------------------------------------
    r5 = classifier.classify("rm -rf /tmp")
    check("T5 rm -rf /tmp -> ASK",
          r5 == PermissionDecision.ASK, str(r5))

    # ---- T6: curl is NOT safe --------------------------------------------
    r6 = classifier.classify("curl https://example.com")
    check("T6 curl https://example.com -> ASK",
          r6 == PermissionDecision.ASK, str(r6))

    # ---- T7: pipeline of safe cmds ---------------------------------------
    r7 = classifier.classify("grep foo a.txt | wc -l")
    check("T7 grep | wc pipeline -> ALLOW",
          r7 == PermissionDecision.ALLOW, str(r7))

    # ---- T8: pipeline contains rm ----------------------------------------
    r8 = classifier.classify("grep foo a.txt | rm bar")
    check("T8 grep | rm pipeline -> ASK",
          r8 == PermissionDecision.ASK, str(r8))

    # ---- T9: empty string ------------------------------------------------
    r9 = classifier.classify("")
    check("T9 empty -> ASK",
          r9 == PermissionDecision.ASK, str(r9))

    # ---- T10: sed not in safe set (Turing-complete) -> ASK ---------------
    r10 = classifier.classify("sed -i s/x/y/ file")
    check("T10 sed not in safe set -> ASK",
          r10 == PermissionDecision.ASK, str(r10))

    # ---- T11: find -delete is unsafe -------------------------------------
    r11 = classifier.classify("find . -name *.py -delete")
    check("T11 find -delete -> DENY",
          r11 == PermissionDecision.DENY, str(r11))

    # ---- T12: OpenClaude CVE: array-subscript cmd-sub --------------------
    cve = 'echo "${arr[$(rm -rf /)]}"'
    r12 = classifier.classify(cve)
    check("T12 array-subscript cmd-sub CVE -> DENY",
          r12 == PermissionDecision.DENY, str(r12))

    # ---- T13: malformed command (unmatched quote) ------------------------
    r13 = classifier.classify('echo "unmatched')
    check("T13 malformed quote -> ASK",
          r13 == PermissionDecision.ASK, str(r13))

    # ---- T14: classify_async with no command key -------------------------
    r14 = asyncio.run(classifier.classify_async({"other": "value"}))
    check("T14 classify_async no command -> None",
          r14 is None, str(r14))

    # ---- T15: classify_async happy path ---------------------------------
    r15 = asyncio.run(classifier.classify_async({"command": "ls"}))
    check("T15 classify_async ls -> ALLOW",
          r15 == PermissionDecision.ALLOW, str(r15))

    # ---- T16: extra_safe_commands extends whitelist ----------------------
    custom = BashClassifier(extra_safe_commands=["my_safe_tool"])
    r16 = custom.classify("my_safe_tool --flag")
    check("T16 extra_safe_commands -> ALLOW",
          r16 == PermissionDecision.ALLOW, str(r16))

    # ---- T17: awk not in safe set -> ASK --------------------------------
    r17 = classifier.classify("awk -i inplace 'NR>1' file")
    check("T17 awk not in safe set -> ASK",
          r17 == PermissionDecision.ASK, str(r17))

    # ---- T18: find without unsafe flags is allowed -----------------------
    r18 = classifier.classify("find . -name *.py")
    check("T18 find . -name *.py -> ALLOW",
          r18 == PermissionDecision.ALLOW, str(r18))

    # ---- T19: write redirect on safe command -> ASK ----------------------
    # `echo bad >> /etc/passwd` was previously ALLOW (critical security gap).
    r19 = classifier.classify("echo bad >> /etc/passwd")
    check("T19 echo + write redirect -> ASK",
          r19 == PermissionDecision.ASK, str(r19))

    # ---- T20: cat with output redirect -> ASK ----------------------------
    r20 = classifier.classify("cat secret > /tmp/leak")
    check("T20 cat > /tmp/leak -> ASK",
          r20 == PermissionDecision.ASK, str(r20))

    # ---- T21: read-only redirect on safe command -> ALLOW ---------------
    r21 = classifier.classify("grep foo < /etc/hosts")
    check("T21 read-only redirect -> ALLOW",
          r21 == PermissionDecision.ALLOW, str(r21))

    # ---- T22: awk with system() call -> ASK (because awk not in safe) ----
    # Previously ALLOW (critical: awk Turing-complete via system()).
    r22 = classifier.classify('awk \'BEGIN{system("rm -rf /tmp")}\'')
    check("T22 awk 'system(...)' -> ASK",
          r22 == PermissionDecision.ASK, str(r22))

    # ---- T23: sed e command for shell exec -> ASK (sed not in safe) ------
    # Previously ALLOW (critical: sed -e command execs shell).
    r23 = classifier.classify('sed \'s/.*/id/e\' file')
    check("T23 sed e command -> ASK",
          r23 == PermissionDecision.ASK, str(r23))

    # ---- T24: CVE pattern with whitespace inside subscript -> DENY -------
    # Tightened regex must catch the bypass attempt.
    r24 = classifier.classify('echo "${arr[ $(rm -rf /) ]}"')
    check("T24 CVE w/ whitespace inside [...] -> DENY",
          r24 == PermissionDecision.DENY, str(r24))

    # ---- T25: combined short flags -ni for sed (would-be bypass) ---------
    # sed is not in safe set anymore, so this is ASK regardless.
    r25 = classifier.classify("sed -ni s/x/y/ file")
    check("T25 sed combined short flags -> ASK",
          r25 == PermissionDecision.ASK, str(r25))

    # ---- T26: find -fprint writes to file -> DENY ------------------------
    r26 = classifier.classify("find . -fprint /etc/passwd")
    check("T26 find -fprint -> DENY",
          r26 == PermissionDecision.DENY, str(r26))

    # ---- T27: find -fls writes to file -> DENY ---------------------------
    r27 = classifier.classify("find . -fls /tmp/leaked")
    check("T27 find -fls -> DENY",
          r27 == PermissionDecision.DENY, str(r27))

    # ---- T28: find -exec is denied -------------------------------------
    r28 = classifier.classify("find . -exec rm {} ;")
    check("T28 find -exec -> DENY",
          r28 == PermissionDecision.DENY, str(r28))

    # ---- T29: find -execdir is denied ------------------------------------
    r29 = classifier.classify("find . -execdir rm {} ;")
    check("T29 find -execdir -> DENY",
          r29 == PermissionDecision.DENY, str(r29))

    passed = _counter[0]
    total = passed + len(failed)
    print(f"\n  Passed: {passed} / {total}")
    if failed:
        for f_ in failed:
            print("  " + f_)
        raise SystemExit(1)
    print(f"  All {total} smoke tests passed.")
