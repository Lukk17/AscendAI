package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.orchestrator.service.memory.SemanticMemoryClient;
import com.lukk.ascend.ai.orchestrator.service.memory.SemanticMemoryItem;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.ArrayList;
import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatContextAssembler {

    private final UserInstructionService userInstructionService;
    private final SemanticMemoryClient semanticMemoryClient;
    private final SemanticMemoryProperties semanticMemoryProperties;
    private final RagRetrievalService ragRetrievalService;
    private final DocumentIngestionService documentIngestionService;

    @Value("${app.system-prompt}")
    private String baseSystemPrompt;

    public String buildSystemMessage(String userId, String userPrompt) {
        String instructions = userInstructionService.getInstructions(userId);

        List<SemanticMemoryItem> semanticMemory = fetchSemanticMemory(userId, userPrompt);
        String semanticMemoryBlock = buildSemanticMemoryBlock(semanticMemory);

        StringBuilder sb = new StringBuilder(baseSystemPrompt);
        sb.append("\n\nUser Instructions:\n").append(instructions != null ? instructions : "");
        if (!semanticMemoryBlock.isBlank()) {
            sb.append("\n\n").append(semanticMemoryBlock);
        }
        
        log.info("Assembled SystemMessage for user: '{}'. State -> BaseSystemPrompt: YES, UserInstructions: {}, SemanticMemory: {} ({} items)", 
                userId, (instructions != null && !instructions.isBlank()) ? "YES" : "NO", !semanticMemoryBlock.isBlank() ? "YES" : "NO", semanticMemory != null ? semanticMemory.size() : 0);
                
        return sb.toString();
    }

    public String buildUserMessage(String originalPrompt, MultipartFile document, String embeddingProvider) {
        String userPrompt = originalPrompt;

        if (document != null && !document.isEmpty()) {
            userPrompt += documentIngestionService.processDocument(document);
        }

        String ragContext = ragRetrievalService.retrieveContext(userPrompt, embeddingProvider);
        if (!ragContext.isBlank()) {
            userPrompt += "\n\n" + ragContext;
        }

        log.info("Assembled UserMessage. State -> DocumentAttached: {}, RAG Context Injected: {}", 
                (document != null && !document.isEmpty()) ? "YES" : "NO", !ragContext.isBlank() ? "YES" : "NO");

        return userPrompt;
    }

    private List<SemanticMemoryItem> fetchSemanticMemory(String userId, String userPrompt) {
        try {
            return semanticMemoryClient.search(userId, userPrompt, semanticMemoryProperties.getSearchLimit());
        } catch (Exception e) {
            log.warn("Semantic memory retrieval failed for userId={}: {}", userId, e.getMessage());
            return List.of();
        }
    }

    private String buildSemanticMemoryBlock(List<SemanticMemoryItem> items) {
        if (items == null || items.isEmpty()) {
            return "";
        }

        List<String> lines = new ArrayList<>();
        for (SemanticMemoryItem item : items) {
            if (item == null || item.text() == null || item.text().isBlank()) {
                continue;
            }
            lines.add("- " + item.text());
        }

        if (lines.isEmpty()) {
            return "";
        }

        return "User memory (may be relevant):\n" + String.join("\n", lines);
    }
}
