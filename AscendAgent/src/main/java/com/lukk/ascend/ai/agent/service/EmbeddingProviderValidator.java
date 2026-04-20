package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties.EmbeddingConfig;
import com.lukk.ascend.ai.agent.exception.IncompatibleEmbeddingException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.Map;
import java.util.Optional;
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class EmbeddingProviderValidator {

    private static final int DIMENSIONS_768 = 768;
    private static final int DIMENSIONS_1536 = 1536;

    private static final Map<Integer, Set<String>> INCOMPATIBLE_CHAT_PROVIDERS = Map.of(
            DIMENSIONS_768, Set.of("openai"),
            DIMENSIONS_1536, Set.of("lmstudio")
    );

    private final EmbeddingProviderProperties embeddingProviderProperties;
    private final AiProviderProperties aiProviderProperties;

    public void validate(String chatProvider, String embeddingProvider) {
        String resolvedChatProvider = resolveProvider(chatProvider, aiProviderProperties.getDefaultProvider());
        String resolvedEmbeddingProvider = resolveProvider(embeddingProvider, embeddingProviderProperties.getDefaultProvider());

        EmbeddingConfig embeddingConfig = embeddingProviderProperties.getProviders().get(resolvedEmbeddingProvider);
        if (embeddingConfig == null) {
            throw new IllegalArgumentException(
                    "Unknown embedding provider: '%s'. Available: %s"
                            .formatted(resolvedEmbeddingProvider, embeddingProviderProperties.getProviders().keySet()));
        }

        int embeddingDimensions = embeddingConfig.getDimensions();
        Set<String> incompatible = INCOMPATIBLE_CHAT_PROVIDERS.getOrDefault(embeddingDimensions, Set.of());

        if (incompatible.contains(resolvedChatProvider)) {
            int requiredDimensions = embeddingDimensions == DIMENSIONS_768 ? DIMENSIONS_1536 : DIMENSIONS_768;
            throw new IncompatibleEmbeddingException(
                    resolvedChatProvider,
                    resolvedEmbeddingProvider,
                    embeddingDimensions,
                    requiredDimensions);
        }
    }

    private String resolveProvider(String provider, String defaultValue) {
        return Optional.ofNullable(provider)
                .filter(StringUtils::hasText)
                .map(String::trim)
                .map(String::toLowerCase)
                .orElse(defaultValue);
    }
}
