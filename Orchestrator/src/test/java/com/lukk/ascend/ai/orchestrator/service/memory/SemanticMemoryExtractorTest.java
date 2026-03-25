package com.lukk.ascend.ai.orchestrator.service.memory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.orchestrator.service.ChatModelResolver;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.after;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SemanticMemoryExtractorTest {

    private static final String DEFAULT_USER_ID = "user1";
    private static final String DEFAULT_USER_TEXT = "My dog is named Rex";
    private static final String DEFAULT_PROVIDER = "lmstudio";

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @Mock
    private SemanticMemoryClient memoryClient;

    @Mock
    private ObjectMapper objectMapper;

    @Mock
    private ChatModel chatModel;

    @InjectMocks
    private SemanticMemoryExtractor extractor;

    @Test
    void extract_WhenValidFactsReturned_ThenSavesMemoryAsynchronously() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String jsonResponse = "[\"User has a dog named Rex\"]";
        ChatResponse mockResponse = createMockChatResponse(jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);

        List<String> parsedFacts = List.of("User has a dog named Rex");
        when(objectMapper.readValue(eq(jsonResponse), any(TypeReference.class))).thenReturn(parsedFacts);

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER);

        // then
        // Since Virtual Thread executes asynchronously, use timeout verification
        verify(memoryClient, timeout(2000)).insertMemory(DEFAULT_USER_ID, "User has a dog named Rex");
    }

    @Test
    void extract_WhenEmptyFactsReturned_ThenDoesNotSaveMemory() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String jsonResponse = "[]";
        ChatResponse mockResponse = createMockChatResponse(jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);

        List<String> parsedFacts = List.of();
        when(objectMapper.readValue(eq(jsonResponse), any(TypeReference.class))).thenReturn(parsedFacts);

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any());
    }

    @Test
    void extract_WhenAiThrowsException_ThenHandlesGracefully() {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(Prompt.class))).thenThrow(new RuntimeException("AI Provider Down"));

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any());
    }
    
    @Test
    void extract_WhenJsonProcessingException_ThenHandlesGracefully() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String invalidJson = "Invalid output";
        ChatResponse mockResponse = createMockChatResponse(invalidJson);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);

        when(objectMapper.readValue(eq(invalidJson), any(TypeReference.class)))
                .thenThrow(new JsonProcessingException("Malformatted JSON") {});

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any());
    }

    private void setupProviderConfig(String extractionModel) {
        ProviderConfig config = new ProviderConfig();
        config.setMemoryExtractionModel(extractionModel);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(DEFAULT_PROVIDER, config));
    }

    private ChatResponse createMockChatResponse(String content) {
        AssistantMessage assistantMessage = new AssistantMessage(content);
        Generation generation = new Generation(assistantMessage);
        return new ChatResponse(List.of(generation));
    }
}
