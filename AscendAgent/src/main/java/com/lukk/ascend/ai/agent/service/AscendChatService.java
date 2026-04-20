package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryExtractor;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.messages.Message;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class AscendChatService {

    private final AiProviderProperties aiProviderProperties;
    private final ChatContextAssembler contextAssembler;
    private final ChatHistoryService historyService;
    private final ChatExecutor chatExecutor;
    private final EmbeddingProviderValidator embeddingProviderValidator;
    private final SemanticMemoryExtractor semanticMemoryExtractor;

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId,
                             String provider, String model, String embeddingProvider) {
        log.info("Starting orchestration for user: {}", userId);

        String activeEmbeddingProvider = Optional.ofNullable(embeddingProvider)
                .orElseGet(() -> Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
                        .map(AiProviderProperties.ProviderConfig::getDefaultEmbedding)
                        .orElse(null));

        embeddingProviderValidator.validate(provider, activeEmbeddingProvider);

        String systemText = contextAssembler.buildSystemMessage(userId, prompt, activeEmbeddingProvider);
        String userText = contextAssembler.buildUserMessage(prompt, document, activeEmbeddingProvider);

        List<Message> history = historyService.loadHistory(userId);

        AiResponse response = chatExecutor.execute(userId, systemText, userText, history, image, provider, model);

        historyService.saveHistory(userId, userText, response.content());

        semanticMemoryExtractor.extract(userId, prompt, provider, model, activeEmbeddingProvider);

        return response;
    }
}
