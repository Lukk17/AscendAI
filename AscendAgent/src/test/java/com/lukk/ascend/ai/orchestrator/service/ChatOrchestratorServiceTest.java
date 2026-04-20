package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.CustomMetadata;
import com.lukk.ascend.ai.orchestrator.service.memory.SemanticMemoryExtractor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatOrchestratorServiceTest {

    private static final String DEFAULT_PROMPT = "Explain this";
    private static final String DEFAULT_USER_ID = "user1";
    private static final String DEFAULT_PROVIDER = "lmstudio";
    private static final String DEFAULT_MODEL = "llama-3";
    private static final String ACTIVE_EMBEDDING = "openai";

    @Mock
    private AiProviderProperties aiProviderProperties;

    @Mock
    private ChatContextAssembler contextAssembler;

    @Mock
    private ChatHistoryService historyService;

    @Mock
    private ChatExecutor chatExecutor;

    @Mock
    private EmbeddingProviderValidator embeddingProviderValidator;

    @Mock
    private SemanticMemoryExtractor semanticMemoryExtractor;

    @InjectMocks
    private ChatOrchestratorService orchestratorService;

    @Test
    void prompt_WhenValidInputs_ThenExecutesAndExtractsMemory() {
        // given
        MultipartFile image = mock(MultipartFile.class);
        MultipartFile doc = mock(MultipartFile.class);

        when(contextAssembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING)).thenReturn("System...");
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, doc, ACTIVE_EMBEDDING)).thenReturn("ProcessedPrompt");

        List<Message> mockHistory = List.of(new UserMessage("Old Msg"));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(mockHistory);

        AiResponse mockResponse = new AiResponse("Expected answer", new CustomMetadata(null, List.of()));
        when(chatExecutor.execute(DEFAULT_USER_ID, "System...", "ProcessedPrompt", mockHistory, image, DEFAULT_PROVIDER, DEFAULT_MODEL))
                .thenReturn(mockResponse);

        // when
        AiResponse result = orchestratorService.prompt(DEFAULT_PROMPT, image, doc, DEFAULT_USER_ID, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);

        // then
        assertThat(result).isNotNull();
        assertThat(result.content()).isEqualTo("Expected answer");

        verify(embeddingProviderValidator).validate(DEFAULT_PROVIDER, ACTIVE_EMBEDDING);
        verify(historyService).saveHistory(DEFAULT_USER_ID, "ProcessedPrompt", "Expected answer");
        verify(semanticMemoryExtractor).extract(DEFAULT_USER_ID, DEFAULT_PROMPT, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);
    }

    @Test
    void prompt_WhenEmbeddingProviderNotProvided_ThenResolvesFromPropertiesAndExecutes() {
        // given
        ProviderConfig config = new ProviderConfig();
        config.setDefaultEmbedding(ACTIVE_EMBEDDING);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(DEFAULT_PROVIDER, config));

        when(contextAssembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING)).thenReturn("System...");
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING)).thenReturn("ProcessedPrompt");

        List<Message> mockHistory = List.of();
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(mockHistory);

        AiResponse mockResponse = new AiResponse("Answer", new CustomMetadata(null, List.of()));
        when(chatExecutor.execute(DEFAULT_USER_ID, "System...", "ProcessedPrompt", mockHistory, null, DEFAULT_PROVIDER, DEFAULT_MODEL))
                .thenReturn(mockResponse);

        // when
        AiResponse result = orchestratorService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID, DEFAULT_PROVIDER, DEFAULT_MODEL, null);

        // then
        assertThat(result.content()).isEqualTo("Answer");
        verify(embeddingProviderValidator).validate(DEFAULT_PROVIDER, ACTIVE_EMBEDDING);
        verify(semanticMemoryExtractor).extract(DEFAULT_USER_ID, DEFAULT_PROMPT, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);
    }
}