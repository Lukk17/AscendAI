package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.dto.SourceFile;
import com.lukk.ascend.ai.agent.memory.CompactionOverride;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryExtractor;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.S3PresignedUrlService;
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
    private final S3PresignedUrlService s3PresignedUrlService;

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId,
                             String provider, String model, String embeddingProvider) {
        return prompt(prompt, image, document, userId, provider, model, embeddingProvider, false,
                CompactionOverride.EMPTY);
    }

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId,
                             String provider, String model, String embeddingProvider, boolean attachSources) {
        return prompt(prompt, image, document, userId, provider, model, embeddingProvider, attachSources,
                CompactionOverride.EMPTY);
    }

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId,
                             String provider, String model, String embeddingProvider, boolean attachSources,
                             CompactionOverride compactionOverride) {
        log.info("Starting orchestration for user: {} (attachSources={}, compactionOverride={})",
                userId, attachSources, compactionOverride);

        String activeEmbeddingProvider = Optional.ofNullable(embeddingProvider)
                .orElseGet(() -> Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
                        .map(AiProviderProperties.ProviderConfig::getDefaultEmbedding)
                        .orElse(null));

        embeddingProviderValidator.validate(provider, activeEmbeddingProvider);

        AssembledSystemMessages systemMessages = contextAssembler.buildSystemMessages(userId, prompt, activeEmbeddingProvider);
        BuiltUserMessage userMessage = contextAssembler.buildUserMessage(prompt, document, activeEmbeddingProvider);

        List<Message> history = historyService.loadHistory(userId);

        AiResponse response = chatExecutor.execute(userId, systemMessages, userMessage.text(), history, image, provider, model);

        String resolvedPrimaryProvider = Optional.ofNullable(provider).orElse(aiProviderProperties.getDefaultProvider());
        historyService.saveHistory(userId, userMessage.text(), response.content(),
                resolvedPrimaryProvider, compactionOverride != null ? compactionOverride : CompactionOverride.EMPTY);

        semanticMemoryExtractor.extract(userId, prompt, provider, model, activeEmbeddingProvider);

        if (attachSources) {
            List<SourceFile> attached = userMessage.ragRetrievalRan()
                    ? s3PresignedUrlService.presignAll(userMessage.sources())
                    : List.of();
            response = response.withSources(attached);
        }

        return response;
    }
}
