---
name: notebooklm-context
description: Use the local NotebookLM Context Vault to save, search, retrieve, and export user-supplied NotebookLM notes for Codex tasks.
---

# NotebookLM Context Vault

Use the `notebooklm-context` MCP tools when the user asks to preserve NotebookLM material or wants prior context retrieved for a task.

NotebookLM is not directly connected in this environment. Treat pasted notes, exported text, and files the user deliberately supplies as the source material. Save them with `context_add`; use `context_search` before answering from the vault; use `context_get` when an exact entry is needed; use `context_export` for a bounded context pack.

Never claim infinite context. Retrieval is ranked and bounded to protect prompt quality. Cite the entry IDs returned by the tool when explaining which vault material informed an answer. Do not store API keys, passwords, or other secrets.

## NotebookLM workflow

1. In NotebookLM, copy a source passage or response (or export a note as text/Markdown).
2. Ask Codex to save it, including a useful title and optional tags.
3. Later, ask Codex to search the vault for the decisions or evidence relevant to the current task.
4. If a large synthesis is needed, ask for a focused context pack with a specific question rather than dumping the entire vault.

This plugin is local-first and inspectable. The vault path defaults to `~/.codex/notebooklm-context.jsonl`; set `NOTEBOOKLM_CONTEXT_FILE` to relocate it. NotebookLM remains the external authoring/source environment, while the vault provides durable Codex retrieval.
