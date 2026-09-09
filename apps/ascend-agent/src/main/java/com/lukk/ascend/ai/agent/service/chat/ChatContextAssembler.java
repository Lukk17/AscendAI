package com.lukk.ascend.ai.agent.service.chat;
import com.lukk.ascend.ai.agent.service.user.UserInstructionService;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalService;
import com.lukk.ascend.ai.agent.service.ingestion.DocumentIngestionService;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryClient;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryItem;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
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

    public String buildSystemMessage(String userId, String userPrompt, String embeddingProvider) {
        return buildSystemMessages(userId, userPrompt, embeddingProvider).combined();
    }

    public AssembledSystemMessages buildSystemMessages(String userId, String userPrompt, String embeddingProvider) {
        String instructions = userInstructionService.getInstructions(userId);

        List<SemanticMemoryItem> semanticMemory = fetchSemanticMemory(userId, userPrompt, embeddingProvider);
        String semanticMemoryBlock = buildSemanticMemoryBlock(semanticMemory);

        StringBuilder dynamic = new StringBuilder();
        dynamic.append("User Instructions:\n").append(instructions != null ? instructions : "");
        if (!semanticMemoryBlock.isBlank()) {
            dynamic.append("\n\n").append(semanticMemoryBlock);
        }

        log.info("Assembled SystemMessage for user: '{}'. State -> BaseSystemPrompt: YES, UserInstructions: {}, SemanticMemory: {} ({} items)",
                userId, (instructions != null && !instructions.isBlank()) ? "YES" : "NO", !semanticMemoryBlock.isBlank() ? "YES" : "NO", semanticMemory != null ? semanticMemory.size() : 0);

        return new AssembledSystemMessages(baseSystemPrompt, dynamic.toString());
    }

    public BuiltUserMessage buildUserMessage(String originalPrompt, MultipartFile document, String embeddingProvider) {
        String userPrompt = originalPrompt;

        if (document != null && !document.isEmpty()) {
            userPrompt += documentIngestionService.processDocument(document);
        }

        RagRetrievalResult retrieval = ragRetrievalService.retrieve(userPrompt, embeddingProvider);
        if (!retrieval.context().isBlank()) {
            userPrompt += "\n\n" + retrieval.context();
        }

        log.info("Assembled UserMessage. State -> DocumentAttached: {}, RAG Context Injected: {}",
                (document != null && !document.isEmpty()) ? "YES" : "NO", !retrieval.context().isBlank() ? "YES" : "NO");

        return new BuiltUserMessage(userPrompt, retrieval.sources(), retrieval.retrievalRan());
    }

    private List<SemanticMemoryItem> fetchSemanticMemory(String userId, String userPrompt, String embeddingProvider) {
        try {
            return semanticMemoryClient.search(userId, userPrompt, semanticMemoryProperties.getSearchLimit(), embeddingProvider);
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
