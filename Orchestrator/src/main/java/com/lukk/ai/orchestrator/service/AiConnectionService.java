package com.lukk.ai.orchestrator.service;

import com.lukk.ai.orchestrator.dto.AiResponse;
import com.lukk.ai.orchestrator.dto.CustomMetadata;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class AiConnectionService {

    private final ChatClient chatClient;

    public AiResponse prompt(String userPrompt) {
        // 1. Call the client to get the full ChatResponse object
        ChatResponse chatResponse = chatClient.prompt()
                .user(userPrompt)
                .call()
                .chatResponse();

        // 2. Extract the content and the metadata
        assert chatResponse != null;
        String content = chatResponse.getResult().getOutput().getText();

        /*
         * This stream operation will not capture the names of the tools used because it inspects the FINAL ChatResponse from the AI model.
         *
         * The high-level `.call().chatResponse()` API automatically handles the entire multi-step tool-calling process:
         * 1. The client sends the user prompt.
         * 2. The AI model responds with a request to call a tool (e.g., `getCurrentWeather`).
         * 3. The `ChatClient` intercepts this, executes the tool, and sends the tool's output back to the model.
         * 4. The AI model processes the tool's output and generates a final, human-readable text response.
         *
         * The `chatResponse` object available here is the result of step 4. At this point, the tool has already been called and its
         * results have been used. The final `AssistantMessage` contains the natural language answer for the user, not the intermediate
         * tool call requests. As a result, the `getToolCalls()` list on this message will be empty.
         */
        List<String> toolsUsed = chatResponse.getResults().stream()
                .map(Generation::getOutput)
                .flatMap(output -> output.getToolCalls().stream())
                .map(AssistantMessage.ToolCall::name)
                .toList();

        CustomMetadata metadata = new CustomMetadata(chatResponse.getMetadata(), toolsUsed);

        // 3. Return your custom DTO
        return new AiResponse(content, metadata);
    }
}
