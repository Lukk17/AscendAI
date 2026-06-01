# 6. Runtime View

---

### Scenario 1: Service startup

```mermaid
sequenceDiagram
    participant Docker as Docker / OS
    participant Uvicorn as Uvicorn
    participant Lifespan as FastAPI Lifespan
    participant Warmup as warmup_client task
    participant Qdrant as Qdrant

    Docker->>Uvicorn: start process
    Uvicorn->>Lifespan: trigger lifespan startup
    Lifespan->>Warmup: asyncio.create_task(warmup_client())
    Lifespan->>Lifespan: MCP lifespan init
    Lifespan->>Uvicorn: yield (app is serving)
    Note over Uvicorn: /health returns 503 (is_ready=False)
    loop up to 60 attempts × 5s
        Warmup->>Qdrant: client.search("startup_warmup", "system_warmup")
        alt Qdrant responds
            Warmup->>Warmup: is_ready = True
            Note over Uvicorn: /health returns 200
        else exception
            Warmup->>Warmup: sleep 5s, retry
        end
    end
```

Source: `src/main.py:28-55`, `src/main.py:85-90`.

---

### Scenario 2: Memory insert (REST path)

```mermaid
sequenceDiagram
    participant Caller as AscendAgent
    participant REST as rest_endpoints.insert_memory
    participant Factory as get_memory_client()
    participant Client as AscendMemoryClient
    participant Mem0 as mem0.Memory
    participant Embedding as Embedding provider
    participant Qdrant as Qdrant

    Caller->>REST: POST /api/v1/memory/insert {user_id, text, provider?}
    REST->>Factory: get_memory_client(provider or default)
    Factory-->>REST: AscendMemoryClient (cached singleton)
    REST->>Client: client.add(user_id, text=text)
    Client->>Mem0: memory.add(messages=[{role:user, content:text}], user_id, infer=False)
    Mem0->>Embedding: POST /embeddings {text}
    Embedding-->>Mem0: vector
    Mem0->>Qdrant: upsert vector + metadata
    Qdrant-->>Mem0: ok
    Mem0-->>Client: {results: [{id, memory, event, ...}]}
    Client-->>REST: list[dict]
    REST-->>Caller: 200 [{id, memory, event, ...}]
```

Source: `src/api/rest/rest_endpoints.py:43-62`, `src/service/memory_client.py:118-138`.

---

### Scenario 3: Memory search

```mermaid
sequenceDiagram
    participant Caller as AscendAgent
    participant REST as rest_endpoints.search_memory
    participant Client as AscendMemoryClient
    participant Mem0 as mem0.Memory
    participant Embedding as Embedding provider
    participant Qdrant as Qdrant

    Caller->>REST: GET /api/v1/memory/search?user_id=U&query=Q&limit=5
    REST->>Client: client.search(query=Q, user_id=U, limit=5)
    Client->>Mem0: memory.search(query=Q, user_id=U, limit=5)
    Mem0->>Embedding: POST /embeddings {query}
    Embedding-->>Mem0: query vector
    Mem0->>Qdrant: cosine search, filter user_id=U, top-5
    Qdrant-->>Mem0: [{id, memory, score, ...}]
    Mem0-->>Client: {results: [...]}
    Client-->>REST: list[dict]
    REST-->>Caller: 200 [...]
```

Source: `src/api/rest/rest_endpoints.py:20-32`, `src/service/memory_client.py:109-116`.

---

### Scenario 4: Memory wipe (workaround path)

The standard mem0ai `delete_all` resets the entire collection. The workaround fetches all memories for the user, then
deletes them one by one.

```mermaid
sequenceDiagram
    participant Caller
    participant REST as rest_endpoints.wipe_memory
    participant Client as AscendMemoryClient
    participant Mem0 as mem0.Memory
    participant Qdrant as Qdrant

    Caller->>REST: POST /api/v1/memory/wipe?user_id=U
    REST->>Client: client.wipe_user(user_id=U)
    Client->>Mem0: memory.get_all(user_id=U)
    Mem0->>Qdrant: filter user_id=U
    Qdrant-->>Mem0: [{id, ...}, ...]
    loop for each memory
        Client->>Mem0: memory.delete(memory_id=id)
        Mem0->>Qdrant: delete point
    end
    Client-->>REST: (void)
    REST-->>Caller: 200 {status: success}
```

Source: `src/service/memory_client.py:148-166`.

---

### Scenario 5: MCP tool call

The MCP path calls the same `get_memory_client()` factory used by REST. The only difference is that the MCP
`memory_insert` tool does not accept `messages`; it accepts only `text`. The JSON-RPC session must be initialized
first (`method: initialize`) to obtain a session ID returned in `MCP-Session-Id`.

Source: `src/api/mcp/mcp_server.py`.
