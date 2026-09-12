# NotebookLM Context Vault

This Codex plugin is a local bridge for NotebookLM workflows. NotebookLM does not expose a
callable connector in the current Codex environment, so the plugin does not pretend to browse
your notebooks. Instead, you deliberately paste or export NotebookLM material into the vault,
then Codex can search and assemble the relevant context later.

## Tools

- `context_add` — save a titled note, excerpt, or decision with source and tags.
- `context_search` — ranked lexical search with short excerpts and stable IDs.
- `context_get` — retrieve one complete entry by ID.
- `context_export` — build a focused Markdown context pack for the current task.

The default vault is `%USERPROFILE%\\.codex\\notebooklm-context.jsonl` on Windows or
`~/.codex/notebooklm-context.jsonl` elsewhere. Set `NOTEBOOKLM_CONTEXT_FILE` to move it.

## Workflow

1. Ask NotebookLM for the specific source passage, decision, or synthesis you want to preserve.
2. Give that text to Codex and ask it to save it with a useful title and tags.
3. In a later task, ask Codex to search the vault for the decisions relevant to that task.
4. Use an explicitly scoped query for `context_export`; do not dump the whole vault into every
   prompt.

This is durable retrieval, not literally infinite context. The vault can grow, but each task still
needs a bounded, relevant context pack. Never save API keys, passwords, or access tokens.
