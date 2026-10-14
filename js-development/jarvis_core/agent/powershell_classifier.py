"""LAYER: Agent — native PowerShell syntax inspection, never command evaluation.

THE BIG PICTURE: Bash syntax cannot establish Windows command safety.
THE FLOW: native ParseInput -> literal command structure -> scoped allowlist.
"""
from __future__ import annotations
import asyncio
import base64
import json
import re
from pathlib import Path

from jarvis_core.agent.execution import powershell_path, ProcessRunner
from jarvis_core.agent.permissions import PermissionDecision
from jarvis_core.config import JARVIS_ROOT

_PARSE = r'''
$tokens=$null; $errors=$null
$source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SOURCE__'))
$ast=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
$allowed=@("ScriptBlockAst","NamedBlockAst","PipelineAst","CommandAst","CommandParameterAst","StringConstantExpressionAst","ConstantExpressionAst")
$structure=@($ast.FindAll({param($n) $n.GetType().Name -notin $allowed},$true))
$bad=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -or
 $n -is [System.Management.Automation.Language.ScriptBlockExpressionAst] -or
 $n -is [System.Management.Automation.Language.SubExpressionAst] -or
 $n -is [System.Management.Automation.Language.VariableExpressionAst] -or
 $n -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -or
 $n -is [System.Management.Automation.Language.TypeExpressionAst] -or
 $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -or
 $n -is [System.Management.Automation.Language.RedirectionAst]},$true))
$commands=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true) | ForEach-Object {
 $parts=@($_.CommandElements | ForEach-Object { @{type=$_.GetType().Name;text=$_.Extent.Text} })
 @{name=$_.GetCommandName();operator=$_.InvocationOperator.ToString();parts=$parts}
})
@{errors=@($errors).Count;bad=($bad.Count+$structure.Count);commands=$commands} | ConvertTo-Json -Depth 8 -Compress
'''

_SAFE = {"get-location", "write-output", "get-childitem", "get-content", "test-path", "get-item",
         "get-process", "get-ciminstance", "select-object", "format-table", "format-list", "convertto-json"}
_PARAMS = {"path", "literalpath", "recurse", "file", "directory", "name", "raw", "totalcount", "tail",
           "property", "first", "last", "skip", "depth", "compress", "autosize", "wrap", "expandproperty", "classname", "id"}
_CLASSES = {"win32_computersystem", "win32_processor", "win32_operatingsystem", "win32_videocontroller"}


def _literal(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1].replace("''", "'")
    return text


class PowerShellClassifier:
    def __init__(self, root: Path = JARVIS_ROOT) -> None:
        self.root = Path(root).resolve()

    async def classify_async(self, tool_input: dict) -> PermissionDecision:
        source = str(tool_input.get("command", ""))
        script = _PARSE.replace("__SOURCE__", base64.b64encode(source.encode()).decode())
        try:
            encoded = base64.b64encode(script.encode("utf-16-le")).decode()
            result = await ProcessRunner().run([powershell_path(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                              cwd=str(self.root), timeout=5)
            if result.is_error:
                return PermissionDecision.ASK
            report = json.loads(result.output["stdout"])
        except (ValueError, OSError):
            return PermissionDecision.ASK
        if report["errors"] or report["bad"] or not report["commands"]:
            return PermissionDecision.ASK
        for index, command in enumerate(report["commands"]):
            name = str(command.get("name") or "").lower()
            if name not in _SAFE or command["operator"] != "Unknown":
                return PermissionDecision.ASK
            parts = command["parts"][1:]
            values = []
            path_values = []
            parameter = None
            for part in parts:
                if part["type"] == "CommandParameterAst":
                    parameter = part["text"][1:].lower()
                    if parameter not in _PARAMS:
                        return PermissionDecision.ASK
                elif part["type"] in {"StringConstantExpressionAst", "ConstantExpressionAst"}:
                    value = _literal(part["text"])
                    values.append(value)
                    if not (parameter in {"totalcount", "tail", "first", "last", "skip", "depth", "id"} and value.isdigit()):
                        path_values.append(value)
                    parameter = None
                else:
                    return PermissionDecision.ASK
            if name == "get-ciminstance" and (len(values) != 1 or values[0].lower() not in _CLASSES):
                return PermissionDecision.ASK
            if name in {"get-content", "get-childitem", "get-item", "test-path"}:
                # Pipeline-bound paths are not literal paths we have checked.
                # E.g. Write-Output '.hearth_token' | Get-Content must not
                # turn an otherwise denied read into an automatic action.
                if index:
                    return PermissionDecision.ASK
                cwd = Path(tool_input.get("cwd") or self.root).resolve()
                if cwd != self.root and self.root not in cwd.parents:
                    return PermissionDecision.ASK
                for value in path_values:
                    if ":" in value and not re.match(r"^[A-Za-z]:[\\/]", value):
                        return PermissionDecision.DENY
                    if name in {"get-content", "get-item"} and any(c in value for c in "*?[]"):
                        return PermissionDecision.ASK
                    path = (Path(tool_input.get("cwd") or self.root) / value).resolve()
                    if path != self.root and self.root not in path.parents:
                        return PermissionDecision.ASK
                    if any(p.lower().startswith(".env") or p.lower() in {".hearth_token", ".git", "credentials"} for p in path.parts):
                        return PermissionDecision.DENY
        return PermissionDecision.ALLOW


if __name__ == "__main__":
    print(asyncio.run(PowerShellClassifier().classify_async({"command": "Get-Location"})))
