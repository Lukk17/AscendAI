package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.CustomMetadata;
import com.lukk.ascend.ai.orchestrator.exception.AiGenerationException;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.vectorstore.QuestionAnswerAdvisor;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class AiConnectionService {

    public static final String USER_ID_KEY = "user_id";
    private final ChatClient chatClient;
    private final VectorStore vectorStore;

    /**
     * Sends a prompt to the AI model and retrieves the response.
     * <p>
     * This method orchestrates the full chat interaction, including tool execution.
     * The AI model may call registered tools (functions) to gather information
     * before providing the final answer.
     * </p>
     *
     * @param userPrompt The user's input message.
     * @param userId     The ID of the user triggering the prompt, for context.
     * @return An {@link AiResponse} containing the generated text and metadata
     * (including tools used).
     * @throws AiGenerationException if the chat client returns a null response.
     */
    public AiResponse prompt(String userPrompt, String userId) {
        ChatResponse chatResponse = chatClient.prompt()
                .user(userPrompt)
                .advisors(QuestionAnswerAdvisor.builder(vectorStore)
                        .searchRequest(SearchRequest.builder().query(userPrompt).topK(5).build())
                        .build())
                .advisors(a -> a.param(USER_ID_KEY, userId))
                .toolContext(Map.of(USER_ID_KEY, userId))
                .call()
                .chatResponse();

        if (chatResponse == null) {
            throw new AiGenerationException("Received null response from ChatClient");
        }

        String content = chatResponse.getResult().getOutput().getText();
        List<String> toolsUsed = extractExecutedToolNames(chatResponse);

        CustomMetadata metadata = new CustomMetadata(chatResponse.getMetadata(), toolsUsed);

        return new AiResponse(content, metadata);
    }

    private List<String> extractExecutedToolNames(ChatResponse chatResponse) {
        return chatResponse.getResults().stream()
                .map(Generation::getOutput)
                .flatMap(output -> output.getToolCalls().stream())
                .map(AssistantMessage.ToolCall::name)
                .toList();
    }
}
