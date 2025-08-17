# AI Orchestrator

Based on:
https://github.com/spring-projects/spring-ai-examples/tree/main/model-context-protocol/brave

---

This project is the central hub of the AI system, acting as an orchestrator.  
It's a Spring Boot application that provides a REST API to connect user prompts with a Large Language Model (LLM).  
Crucially, it extends the LLM's capabilities by dynamically discovering and integrating external tools via the Model Context Protocol (MCP).  

---

## Architecture Overview
The orchestrator manages the flow of information between the user, the LLM, and any connected MCP tool servers.

```
A[User] -- HTTP POST /prompt --> B(Orchestrator);
B -- 1. Starts & Manages --> C[MCP Weather Server (via STDIO)];
B -- 2. Sends Prompt --> D[LLM (LM Studio)];
D -- 3. Sees Tool & Decides to Use --> B;
B -- 4. Executes Tool Call --> C;
C -- 5. Returns Tool Result --> B;
B -- 6. Sends Result to LLM --> D;
D -- 7. Generates Final Answer --> B;
B -- 8. Returns Final Answer --> A;```
```

A text-based representation of the data flow:  

1. A User sends a prompt to the Orchestrator's /prompt API endpoint. 
2. The Orchestrator forwards this prompt to the connected LLM (e.g., running in LM Studio). 
3. The Orchestrator has already discovered the tools available from the MCP Weather Server. It makes these tools available to the LLM. 
4. If the LLM decides a tool is needed to answer the prompt, it sends a tool-call request back to the Orchestrator. 
5. The Orchestrator executes the function on the appropriate MCP server and returns the result to the LLM. 
6. The LLM uses the tool's output to generate a final, informed response, which the Orchestrator sends back to the user.

---

## How to Run and Test

Run the Orchestrator
```
./gradlew bootRun
```
or
```
gradlew.bat bootRun
```

Test API:
```
curl -X POST http://localhost:9999/prompt \
-H "Content-Type: application/json" \
-d '{"prompt": "what is the weather like in warsaw?"}'
```

---

## Configuration

The application's behavior is heavily configured through several key files.

MCP Client:   
`spring.ai.mcp.client` section enables the orchestrator's MCP capabilities.  
It's configured to find and manage local MCP servers via the mcp-servers-config.json file.  

OpenAI Client:  
`spring.ai.openai` section points the application to your local LLM instance.  
The default base-url is set for LM Studio.  


`mcp-servers-config.json`
This file acts as a manifest, telling the orchestrator which local MCP servers to start and manage.  

⚠️ Important: 
The file path to the MCP server JAR is hardcoded.   
Path needs to be updated to match the location of `.jar` file on a system.
