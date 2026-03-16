package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.CustomMetadata;
import com.lukk.ascend.ai.orchestrator.exception.AiGenerationException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClient.ChatClientRequestSpec;
import org.springframework.ai.chat.client.advisor.SimpleLoggerAdvisor;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.util.MimeType;
import org.springframework.util.MimeTypeUtils;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatExecutor {

    private static final String USER_ID_KEY = "user_id";

    private final ChatModelResolver chatModelResolver;
    private final SyncMcpToolCallbackProvider toolCallbackProvider;

    @Value("${app.system-prompt}")
    private String systemPrompt;

    public AiResponse execute(String userId, String systemText, String userText, List<Message> history,
                              MultipartFile image, String provider, String model) {
        log.info("Executing AI Prompt | User: {} | Provider: {} | Model: {} | Prompt Length: {}",
                userId, provider, model, userText.length());

        ChatClient chatClient = buildChatClient(provider, model);

        ChatClientRequestSpec promptBuilder = chatClient.prompt()
                .system(s -> s.text(systemText))
                .messages(history)
                .advisors(new SimpleLoggerAdvisor())
                .advisors(a -> a.param(USER_ID_KEY, userId));

        promptBuilder.toolContext(Map.of(USER_ID_KEY, userId));

        handleImageContext(promptBuilder, userText, image);

        ChatResponse chatResponse = promptBuilder.call().chatResponse();

        if (chatResponse == null) {
            throw new AiGenerationException("Received null response from ChatClient");
        }

        String content = chatResponse.getResult().getOutput().getText();
        List<String> toolsUsed = extractToolsUsed(chatResponse);

        return new AiResponse(content, new CustomMetadata(chatResponse.getMetadata(), toolsUsed));
    }

    private ChatClient buildChatClient(String provider, String model) {
        ChatModel chatModel = chatModelResolver.resolve(provider);

        ChatClient.Builder clientBuilder = ChatClient.builder(chatModel)
                .defaultSystem(systemPrompt)
                .defaultToolCallbacks(toolCallbackProvider.getToolCallbacks());

        if (model != null && !model.isBlank()) {
            clientBuilder.defaultOptions(ChatOptions.builder().model(model).build());
        }

        return clientBuilder.build();
    }

    private void handleImageContext(ChatClientRequestSpec promptBuilder, String userPrompt, MultipartFile image) {
        if (image != null && !image.isEmpty()) {
            try {
                Resource imageResource = new InputStreamResource(image.getInputStream());
                MimeType mimeType = Optional.ofNullable(image.getContentType())
                        .map(MimeType::valueOf)
                        .orElse(MimeTypeUtils.IMAGE_PNG);
                promptBuilder.user(u -> u.text(userPrompt).media(mimeType, imageResource));
                log.info("Attached image resource to prompt with MimeType: {}", mimeType);
            } catch (Exception e) {
                throw new AiGenerationException("Failed to process image upload", e);
            }
        } else {
            promptBuilder.user(userPrompt);
        }
    }

    private List<String> extractToolsUsed(ChatResponse chatResponse) {
        try {
            var output = chatResponse.getResult().getOutput();
            if (output.getToolCalls() == null || output.getToolCalls().isEmpty()) {
                return List.of();
            }
            return output.getToolCalls().stream()
                    .map(AssistantMessage.ToolCall::name)
                    .distinct()
                    .collect(Collectors.toList());
        } catch (Exception e) {
            return List.of();
        }
    }
}
