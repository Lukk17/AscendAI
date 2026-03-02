package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties.ProviderConfig;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.anthropic.AnthropicChatModel;
import org.springframework.ai.anthropic.AnthropicChatOptions;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatModelResolver {

    private static final String TYPE_OPENAI = "openai";
    private static final String TYPE_ANTHROPIC = "anthropic";

    private final AiProviderProperties aiProviderProperties;
    private final Map<String, ChatModel> chatModels = new LinkedHashMap<>();

    @PostConstruct
    void initializeProviders() {
        aiProviderProperties.getProviders().forEach(this::registerProvider);
        log.info("Initialized {} AI providers: {}", chatModels.size(), chatModels.keySet());
    }

    public ChatModel resolve(String provider) {
        String resolvedProvider = Optional.ofNullable(provider)
                .filter(p -> !p.isBlank())
                .orElse(aiProviderProperties.getDefaultProvider());

        return Optional.ofNullable(chatModels.get(resolvedProvider))
                .orElseThrow(() -> new IllegalArgumentException(
                        "AI provider '%s' is not available. Enabled providers: %s"
                                .formatted(resolvedProvider, chatModels.keySet())));
    }

    public ChatModel resolveDefault() {
        return resolve(aiProviderProperties.getDefaultProvider());
    }

    private void registerProvider(String name, ProviderConfig config) {
        if (!config.isEnabled()) {
            log.debug("Skipping disabled AI provider: {}", name);
            return;
        }

        ChatModel chatModel = buildChatModel(name, config);
        chatModels.put(name, chatModel);
        log.info("Registered AI provider: {} (type={}, model={})", name, config.getType(), config.getModel());
    }

    private ChatModel buildChatModel(String name, ProviderConfig config) {
        return switch (config.getType()) {
            case TYPE_OPENAI -> buildOpenAiChatModel(config);
            case TYPE_ANTHROPIC -> buildAnthropicChatModel(config);
            default -> throw new IllegalArgumentException(
                    "Unsupported AI provider type '%s' for provider '%s'".formatted(config.getType(), name));
        };
    }

    private OpenAiChatModel buildOpenAiChatModel(ProviderConfig config) {
        OpenAiApi openAiApi = OpenAiApi.builder()
                .baseUrl(config.getBaseUrl())
                .apiKey(config.getApiKey())
                .build();

        OpenAiChatOptions options = OpenAiChatOptions.builder()
                .model(config.getModel())
                .temperature(config.getTemperature())
                .build();

        return OpenAiChatModel.builder()
                .openAiApi(openAiApi)
                .defaultOptions(options)
                .build();
    }

    private AnthropicChatModel buildAnthropicChatModel(ProviderConfig config) {
        AnthropicApi anthropicApi = AnthropicApi.builder()
                .apiKey(config.getApiKey())
                .build();

        AnthropicChatOptions options = AnthropicChatOptions.builder()
                .model(config.getModel())
                .temperature(config.getTemperature())
                .build();

        return AnthropicChatModel.builder()
                .anthropicApi(anthropicApi)
                .defaultOptions(options)
                .build();
    }
}
