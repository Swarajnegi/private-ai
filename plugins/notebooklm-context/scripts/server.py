"""Small stdio MCP server for a local NotebookLM context vault.

The vault is deliberately plain JSONL: inspectable, append-only, and portable.
It stores excerpts supplied by the user; it does not scrape or impersonate NotebookLM.
"""
from __future__ import annotations
import json, os, re, sys, time, uuid
from pathlib import Path

VAULT = Path(os.environ.get("NOTEBOOKLM_CONTEXT_FILE", Path.home() / ".codex" / "notebooklm-context.jsonl"))

def entries():
    if not VAULT.exists(): return []
    out=[]
    for line in VAULT.read_text(encoding="utf-8").splitlines():
        try: out.append(json.loads(line))
        except json.JSONDecodeError: continue
    return out

def add(title, content, source="NotebookLM", tags=None):
    VAULT.parent.mkdir(parents=True, exist_ok=True)
    item={"id":uuid.uuid4().hex, "title":title.strip(), "content":content,
          "source":source, "tags":tags or [], "created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
    with VAULT.open("a",encoding="utf-8") as f: f.write(json.dumps(item,ensure_ascii=False)+"\n")
    return item

def score(item, query):
    words=[w for w in re.findall(r"\w{2,}",query.lower())]
    text=(item["title"]+" "+item["content"]+" "+" ".join(item.get("tags",[]))).lower()
    return sum(text.count(w) for w in words)

def result(text):
    return {"jsonrpc":"2.0","id":CURRENT_ID,"result":{"content":[{"type":"text","text":text}]}}

def handle(req):
    global CURRENT_ID
    CURRENT_ID=req.get("id")
    method=req.get("method"); p=req.get("params",{})
    if method=="initialize": return {"jsonrpc":"2.0","id":CURRENT_ID,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"notebooklm-context","version":"0.1.0"}}}
    if method=="notifications/initialized": return None
    if method=="tools/list":
        tools=[
          {"name":"context_add","description":"Store a NotebookLM excerpt or note in the local durable vault.","inputSchema":{"type":"object","required":["title","content"],"properties":{"title":{"type":"string"},"content":{"type":"string"},"source":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}}}},
          {"name":"context_search","description":"Search the vault and return ranked matching excerpts with IDs.","inputSchema":{"type":"object","required":["query"],"properties":{"query":{"type":"string"},"limit":{"type":"integer","default":8}}}},
          {"name":"context_get","description":"Retrieve one complete context entry by ID.","inputSchema":{"type":"object","required":["id"],"properties":{"id":{"type":"string"}}}},
          {"name":"context_export","description":"Assemble a Markdown context pack from matching entries for a bounded task prompt.","inputSchema":{"type":"object","required":["query"],"properties":{"query":{"type":"string"},"limit":{"type":"integer","default":8}}}},
        ]
        return {"jsonrpc":"2.0","id":CURRENT_ID,"result":{"tools":tools}}
    if method!="tools/call": return {"jsonrpc":"2.0","id":CURRENT_ID,"error":{"code":-32601,"message":"Unknown method"}}
    name=p.get("name"); a=p.get("arguments",{})
    if name=="context_add":
        x=add(a["title"],a["content"],a.get("source","NotebookLM"),a.get("tags",[])); return result(f"Saved context {x['id']} ({len(x['content'])} characters) to {VAULT}.")
    if name=="context_search":
        found=sorted(((score(x,a["query"]),x) for x in entries()),key=lambda z:z[0],reverse=True)
        found=[x for n,x in found if n>0][:max(1,min(50,int(a.get("limit",8))))]
        return result(json.dumps([{"id":x["id"],"title":x["title"],"source":x["source"],"tags":x.get("tags",[]),"excerpt":x["content"][:700]} for x in found],ensure_ascii=False,indent=2))
    if name=="context_get":
        x=next((x for x in entries() if x["id"]==a["id"]),None)
        return result(json.dumps(x,ensure_ascii=False,indent=2) if x else "No context entry with that ID.")
    if name=="context_export":
        found=sorted(((score(x,a["query"]),x) for x in entries()),key=lambda z:z[0],reverse=True)
        found=[x for n,x in found if n>0][:max(1,min(20,int(a.get("limit",8))))]
        pack="# NotebookLM context pack\n\nQuery: "+a["query"]+"\n\n"+"\n\n---\n\n".join(f"## {x['title']}\nSource: {x['source']}\n\n{x['content']}" for x in found)
        return result(pack if found else "No matching context found.")
    return {"jsonrpc":"2.0","id":CURRENT_ID,"error":{"code":-32602,"message":"Unknown tool"}}

CURRENT_ID=None
for line in sys.stdin:
    try:
        response=handle(json.loads(line))
        if response: print(json.dumps(response,ensure_ascii=False),flush=True)
    except Exception as exc:
        print(json.dumps({"jsonrpc":"2.0","id":CURRENT_ID,"error":{"code":-32000,"message":str(exc)}}),flush=True)
