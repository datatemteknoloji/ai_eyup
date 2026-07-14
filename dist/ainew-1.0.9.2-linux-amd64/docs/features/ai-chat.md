# AI Chat & RAG

The AI Chat page lets you talk to a local LLM about your infrastructure. It can answer questions about server metrics, explain anomalies, and run queries — all with your data, never sent to external APIs.

---

## How it works

```
Your message
    │
    ▼
/api/v1/chat/stream (POST, SSE response)
    │
    ├──► RAG: ChromaDB similarity search
    │    query → top-5 matching chunks from runbooks, metric descriptions
    │
    ├──► Server context: fetch live metrics for selected servers
    │    (CPU, memory, disk, last seen, hostname, OS)
    │
    └──► Ollama chat completion (streaming)
         system prompt:
           "You are an infrastructure AI assistant.
            Context: {rag_chunks}
            Server state: {server_metrics}"
         │
         ▼
    SSE chunks → browser (react-markdown)
```

The response streams word-by-word via Server-Sent Events. There's no waiting for the full response.

---

## Model selection

The chat page shows a model dropdown populated from Ollama's available models. Switch models mid-session — the context resets to a new session with the new model selected.

**Recommended models by use case:**

| Use case | Model |
|---|---|
| Fast answers, low RAM | `qwen2.5:3b` (~2 GB) |
| Balanced quality | `mistral:7b` (~4 GB), `llama3.1:8b` (~5 GB) |
| Complex reasoning | `qwen2.5:14b` (~9 GB), `llama3.1:70b` (GPU required) |
| Turkish language | `qwen2.5:7b` (strong multilingual) |

Pull a model:
```bash
ollama pull mistral:7b
```

The active model can be set as the system default in **Settings → AI**.

---

## Server selection

Select one or more servers in the chat toolbar. The AI receives:
- Server name, IP, OS, hostname
- Current CPU%, memory%, disk%
- Last seen timestamp

Example: select `web-01` and `db-01`, then ask "Which server is using more memory?" — the AI has exact current values.

**AI-Ready servers** — servers marked as AI-Ready have been verified to accept SSH commands. The agent (tool-calling) mode only operates on AI-Ready servers.

---

## RAG (Retrieval-Augmented Generation)

The **RAG** toggle enables semantic search over your knowledge base. When on:
1. Your message is embedded (text → vector)
2. ChromaDB finds the most relevant chunks (runbooks, SOPs, incident history, metric descriptions)
3. These chunks are included in the system prompt

This lets the AI reference your actual runbooks when answering questions like "What do I do when disk is above 90%?"

### Ingest a runbook

```bash
curl -X POST http://localhost:8000/api/v1/rag/ingest \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "When disk usage exceeds 90%, run: find /var/log -name \"*.log\" -mtime +7 -delete",
    "source": "runbook-disk-cleanup",
    "type": "runbook"
  }'
```

Or use the Settings page → RAG tab → upload a document.

### What gets indexed automatically

- Default metric descriptions (built-in, seeded on startup)
- Incident RCA outputs (added after each auto-analysis)

---

## Chat sessions

Each conversation is a session, stored in PostgreSQL. Sessions persist across page reloads and browser restarts.

- Create a new session with **+ Yeni** (New)
- Sessions are listed in the left sidebar with message count and date
- Delete a session with the ✕ button
- Clear all sessions with the trash button

Session messages are associated with the authenticated user — other users don't see your sessions.

---

## How-to: Ask about a specific server

1. Open **Chat** in the sidebar
2. Click the **Sunucu seçin** (Select servers) dropdown
3. Check the servers you want to include
4. Type your question: "Is there anything abnormal on these servers?"
5. The AI responds with context about the selected servers' current state

---

## How-to: Use RAG with a runbook

1. Ingest your runbook (via API or Settings)
2. Enable the **RAG** toggle in the chat toolbar
3. Ask: "How do I clear disk space?"
4. The AI retrieves relevant runbook sections and incorporates them into the answer

---

## How-to: Export AI response as CSV/Excel

When the AI returns a table (Markdown `|...|` format), two export buttons appear below the table:
- **CSV İndir** — downloads as `.csv`
- **Excel İndir** — downloads as `.xlsx`

This is useful for AI-generated reports like "list all servers with disk > 80%" returned as a table.

---

## Explanation: Why local Ollama, not OpenAI/Claude?

Infrastructure data is sensitive — server IPs, hostnames, credentials, system logs. Sending this to external APIs creates:
- Data sovereignty risks (where is it stored? what is the retention?)
- Compliance issues in regulated environments
- Vendor dependency and ongoing per-token cost

Local Ollama keeps all inference on your hardware. The trade-off is quality and speed — a 7B model on a CPU is slower and less capable than GPT-4, but good enough for infra Q&A.

For high-quality reasoning tasks (complex RCA, code generation), run a larger model on a GPU server and point `OLLAMA_URL` at it.

---

## Related

- [Agentic AI](agent.md) — tool-calling mode for executing actions
- [RAG API](../api-reference.md#rag)
- [Chat API](../api-reference.md#ai-chat)
- [Deployment: Ollama config](../deployment.md#environment-variables-reference)
