# AscendAI

This repository contains a multi-module project demonstrating a complete system 
that uses Spring AI's Model Context Protocol (MCP) to extend the capabilities of a Large Language Model (LLM) 
with external, custom tools.

The system is composed of two independent Spring Boot applications that work together: 
an Orchestrator and a standalone MCP Tool Server.

---

## How It Works
The Orchestrator is the brain of the operation. 
When a user sends a prompt to its API, the Orchestrator forwards it to the LLM. 
The Orchestrator also launches and discovers the tools available in the MCP Server, making them available to the LLM. 
This allows the model to answer questions that require external knowledge, such as "What is the weather in Warsaw?".

---

## Detailed Setup and Configuration
For detailed instructions on how to configure, run, and test each application, please see the README.md file located within each module's directory:

➡️ [orchestrator](./Orchestrator/README.md)

➡️ [mcp-server](./MCP/README.md)
