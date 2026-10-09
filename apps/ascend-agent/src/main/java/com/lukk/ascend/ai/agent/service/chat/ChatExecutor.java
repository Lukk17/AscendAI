package com.lukk.ascend.ai.agent.service.chat;
import com.lukk.ascend.ai.agent.service.provider.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.provider.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.provider.ToolCallTracker;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.dto.CustomMetadata;
import com.lukk.ascend.ai.agent.exception.AiGenerationException;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClient.ChatClientRequestSpec;
import org.springframework.ai.chat.client.advisor.SimpleLoggerAdvisor;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.util.InvalidMimeTypeException;
import org.springframework.util.MimeType;
import org.springframework.util.MimeTypeUtils;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

@Service
@Slf4j
public class ChatExecutor {

    private static final String USER_ID_KEY = "user_id";
    private static final String METRIC_MCP_TOOL_DURATION = "mcp.tool.duration";
    private static final String OUTCOME_OK = "ok";
    private static final String OUTCOME_ERROR = "error";
    private static final String OUTCOME_TIMEOUT = "timeout";

    private final ChatModelResolver chatModelResolver;
    private final ToolCallbackProvider toolCallbackProvider;
    private final ChatResponseContentResolver chatResponseContentResolver;
    private final PromptCacheStrategyResolver cacheStrategyResolver;
    private final MeterRegistry meterRegistry;
    private final ToolCallTracker toolCallTracker;

    public ChatExecutor(ChatModelResolver chatModelResolver,
                        ToolCallbackProvider toolCallbackProvider,
                        ChatResponseContentResolver chatResponseContentResolver,
                        PromptCacheStrategyResolver cacheStrategyResolver,
                        MeterRegistry meterRegistry,
                        ToolCallTracker toolCallTracker) {
        this.chatModelResolver = chatModelResolver;
        this.toolCallbackProvider = toolCallbackProvider;
        this.chatResponseContentResolver = chatResponseContentResolver;
        this.cacheStrategyResolver = cacheStrategyResolver;
        this.meterRegistry = meterRegistry;
        this.toolCallTracker = toolCallTracker;
    }

    public AiResponse execute(String userId, String systemText, String userText, List<Message> history,
                              MultipartFile image, String provider, String model) {
        return execute(userId, new AssembledSystemMessages(systemText, ""), userText, history, image, provider, model);
    }

    public AiResponse execute(String userId, AssembledSystemMessages systemMessages, String userText, List<Message> history,
                              MultipartFile image, String provider, String model) {
        log.info("Executing AI Prompt | User: {} | Provider: {} | Model: {} | Prompt Length: {}",
                userId, provider, model, userText.length());

        PromptCacheStrategy strategy = cacheStrategyResolver.resolve(provider);
        ChatOptions decoratedOptions = strategy.buildOptions(model);

        Timer.Sample toolSample = Timer.start(meterRegistry);
        try {
            ChatResponse chatResponse;
            try {
                chatResponse = invoke(userId, systemMessages, userText, history, image, provider, model, decoratedOptions);
            } catch (RuntimeException e) {
                if (!strategy.isCacheConfigError(e)) {
                    throw e;
                }
                log.warn("[PromptCache] provider={} cache call failed, retrying without cache: {}",
                        strategy.providerName(), e.getMessage());
                ChatOptions fallbackOptions = StringUtils.hasText(model)
                        ? ChatOptions.builder().model(model).build() : null;
                chatResponse = invoke(userId, systemMessages, userText, history, image, provider, model, fallbackOptions);
            }

            if (chatResponse == null) {
                recordToolMetrics(toolCallTracker.drain(), OUTCOME_ERROR, toolSample);
                throw new AiGenerationException("Received null response from ChatClient");
            }

            strategy.recordOutcome(userId, chatResponse);

            String content = chatResponseContentResolver.resolveContent(chatResponse);
            List<String> toolsUsed = toolCallTracker.drain();
            recordToolMetrics(toolsUsed, OUTCOME_OK, toolSample);

            return new AiResponse(content, new CustomMetadata(chatResponse.getMetadata(), toolsUsed));
        } catch (RuntimeException e) {
            recordToolMetrics(toolCallTracker.drain(), classifyToolOutcome(e), toolSample);
            throw e;
        }
    }

    private ChatResponse invoke(String userId, AssembledSystemMessages systemMessages, String userText,
                                List<Message> history, MultipartFile image, String provider, String model,
                                ChatOptions options) {
        toolCallTracker.reset();
        ChatClient chatClient = buildChatClient(provider, model, options);

        List<Message> allMessages = new ArrayList<>();
        allMessages.add(new SystemMessage(systemMessages.staticPrefix()));
        if (systemMessages.hasDynamic()) {
            allMessages.add(new SystemMessage(systemMessages.dynamicSuffix()));
        }
        if (history != null && !history.isEmpty()) {
            allMessages.addAll(history);
        }

        ChatClientRequestSpec promptBuilder = chatClient.prompt()
                .messages(allMessages)
                .advisors(new SimpleLoggerAdvisor())
                .advisors(a -> a.param(USER_ID_KEY, userId));

        promptBuilder.toolContext(Map.of(USER_ID_KEY, userId));

        if (options != null) {
            promptBuilder.options(options);
        }

        handleImageContext(promptBuilder, userText, image);

        return promptBuilder.call().chatResponse();
    }

    private ChatClient buildChatClient(String provider, String model, ChatOptions decoratedOptions) {
        ChatModel chatModel = chatModelResolver.resolve(provider);

        ChatClient.Builder clientBuilder = ChatClient.builder(chatModel)
                .defaultToolCallbacks(toolCallbackProvider.getToolCallbacks());

        if (decoratedOptions == null && StringUtils.hasText(model)) {
            clientBuilder.defaultOptions(ChatOptions.builder().model(model).build());
        }

        return clientBuilder.build();
    }

    private void handleImageContext(ChatClientRequestSpec promptBuilder, String userPrompt, MultipartFile image) {
        if (image == null || image.isEmpty()) {
            promptBuilder.user(userPrompt);
            return;
        }
        try {
            Resource imageResource = new InputStreamResource(image.getInputStream());
            MimeType mimeType = resolveImageMimeType(image);
            promptBuilder.user(u -> u.text(userPrompt).media(mimeType, imageResource));
            log.info("Attached image resource to prompt with MimeType: {}", mimeType);
        } catch (Exception e) {
            throw new AiGenerationException("Failed to process image upload", e);
        }
    }

    /**
     * Resolves a never-null {@link MimeType} for the uploaded image. Order:
     * 1. Try {@code Content-Type} header - but reject obviously broken values
     * ({@code null}, blank, no slash, "file", "application/octet-stream").
     * 2. Try filename extension (.jpg, .jpeg, .png, .webp, .gif).
     * 3. Default to {@code image/png}.
     * Logs at INFO when a fallback path is taken, so a malformed client header
     * is visible without poisoning the request.
     */
    MimeType resolveImageMimeType(MultipartFile image) {
        String contentType = image.getContentType();
        if (StringUtils.hasText(contentType) && contentType.contains("/")
                && !"application/octet-stream".equalsIgnoreCase(contentType)) {
            try {
                return MimeType.valueOf(contentType);
            } catch (InvalidMimeTypeException e) {
                log.info("Invalid image Content-Type '{}' - falling back to filename extension", contentType);
            }
        } else if (StringUtils.hasText(contentType)) {
            log.info("Suspect image Content-Type '{}' - falling back to filename extension", contentType);
        }

        String filename = image.getOriginalFilename();
        MimeType byExtension = mimeTypeForExtension(filename);
        if (byExtension != null) {
            return byExtension;
        }

        log.info("Could not infer image MIME from Content-Type or filename '{}' - defaulting to image/png", filename);

        return MimeTypeUtils.IMAGE_PNG;
    }

    private static MimeType mimeTypeForExtension(String filename) {
        if (!StringUtils.hasText(filename)) {
            return null;
        }

        String extension = extractExtension(filename);

        return switch (extension) {
            case "jpg", "jpeg" -> MimeTypeUtils.IMAGE_JPEG;
            case "png" -> MimeTypeUtils.IMAGE_PNG;
            case "webp" -> MimeType.valueOf("image/webp");
            case "gif" -> MimeType.valueOf("image/gif");
            default -> null;
        };
    }

    private static String extractExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        if (dot < 0 || dot == filename.length() - 1) {
            return "";
        }

        return filename.substring(dot + 1).toLowerCase();
    }

    private void recordToolMetrics(List<String> toolsUsed, String outcome, Timer.Sample sample) {
        for (String tool : toolsUsed) {
            sample.stop(Timer.builder(METRIC_MCP_TOOL_DURATION)
                    .tag("tool", tool)
                    .tag("outcome", outcome)
                    .register(meterRegistry));
        }
    }

    static String classifyToolOutcome(Throwable e) {
        Throwable current = e;
        while (current != null) {
            if (current instanceof java.util.concurrent.TimeoutException
                    || current instanceof java.net.SocketTimeoutException) {
                return OUTCOME_TIMEOUT;
            }
            current = current.getCause();
        }
        String message = e.getMessage();
        if (message != null) {
            String lower = message.toLowerCase();
            if (lower.contains("timeout") || lower.contains("timed out")) {
                return OUTCOME_TIMEOUT;
            }
        }
        return OUTCOME_ERROR;
    }

    public <T> T invokeToolWithMetrics(String toolName, Callable<T> toolAction) throws Exception {
        Timer.Sample sample = Timer.start(meterRegistry);
        String outcome = OUTCOME_OK;
        try {
            return toolAction.call();
        } catch (Exception e) {
            outcome = classifyToolOutcome(e);
            throw e;
        } finally {
            sample.stop(Timer.builder(METRIC_MCP_TOOL_DURATION)
                    .tag("tool", toolName)
                    .tag("outcome", outcome)
                    .register(meterRegistry));
        }
    }

}
