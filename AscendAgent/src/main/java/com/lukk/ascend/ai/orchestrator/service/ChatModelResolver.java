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

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatModelResolver {

    private static final String TYPE_OPENAI = "openai";
    private static final String TYPE_ANTHROPIC = "anthropic";
    private static final long DEFAULT_CONNECT_TIMEOUT_SECONDS = 10L;
    private static final long DEFAULT_READ_TIMEOUT_SECONDS = 60L;

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
            case TYPE_OPENAI -> buildOpenAiChatModel(name, config);
            case TYPE_ANTHROPIC -> buildAnthropicChatModel(name, config);
            default -> throw new IllegalArgumentException(
                    "Unsupported AI provider type '%s' for provider '%s'".formatted(config.getType(), name));
        };
    }

    private OpenAiChatModel buildOpenAiChatModel(String name, ProviderConfig config) {
        OpenAiApi openAiApi = OpenAiApi.builder()
                .baseUrl(config.getBaseUrl())
                .apiKey(config.getApiKey())
                .restClientBuilder(RestClient.builder().requestFactory(buildRequestFactory(config.getTimeoutSeconds(), config.isRequiresHttp1())))
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

    private AnthropicChatModel buildAnthropicChatModel(String name, ProviderConfig config) {
        AnthropicApi anthropicApi = AnthropicApi.builder()
                .baseUrl(config.getBaseUrl())
                .apiKey(config.getApiKey())
                .restClientBuilder(RestClient.builder().requestFactory(buildRequestFactory(config.getTimeoutSeconds(), config.isRequiresHttp1())))
                .build();

        AnthropicChatOptions options = AnthropicChatOptions.builder()
                .model(config.getModel())
                .temperature(config.getTemperature())
                .maxTokens(config.getMaxTokens() != null ? config.getMaxTokens() : 4096)
                .build();

        return AnthropicChatModel.builder()
                .anthropicApi(anthropicApi)
                .defaultOptions(options)
                .build();
    }

    @SuppressWarnings("null")
    private ClientHttpRequestFactory buildRequestFactory(Long timeoutSeconds, boolean isHttp1Required) {
        Duration timeout = Duration.ofSeconds(
                Optional.ofNullable(timeoutSeconds).orElse(DEFAULT_READ_TIMEOUT_SECONDS)
        );
        
        HttpClient.Builder builder = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(DEFAULT_CONNECT_TIMEOUT_SECONDS));
        
        Optional.of(isHttp1Required)
                .filter(Boolean::booleanValue)
                .ifPresent(ignored -> builder.version(HttpClient.Version.HTTP_1_1));
        
        HttpClient httpClient = builder.build();
        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(timeout);
        return requestFactory;
    }
}
