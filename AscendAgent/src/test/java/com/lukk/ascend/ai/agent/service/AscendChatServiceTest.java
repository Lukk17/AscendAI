package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.dto.CustomMetadata;
import com.lukk.ascend.ai.agent.dto.SourceFile;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryExtractor;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.S3PresignedUrlService;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
import org.mockito.ArgumentMatchers;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.web.multipart.MultipartFile;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AscendChatServiceTest {

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

    @Mock
    private S3PresignedUrlService s3PresignedUrlService;

    @InjectMocks
    private AscendChatService ascendChatService;

    @Test
    void prompt_WhenValidInputs_ThenExecutesAndExtractsMemory() {
        MultipartFile image = mock(MultipartFile.class);
        MultipartFile doc = mock(MultipartFile.class);

        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("System...", ""));
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, doc, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("ProcessedPrompt", List.of(), true));

        List<Message> mockHistory = List.of(new UserMessage("Old Msg"));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(mockHistory);

        AiResponse mockResponse = new AiResponse("Expected answer", new CustomMetadata(null, List.of()));
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("ProcessedPrompt"), eq(mockHistory), eq(image), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(mockResponse);

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, image, doc, DEFAULT_USER_ID, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);

        assertThat(result).isNotNull();
        assertThat(result.content()).isEqualTo("Expected answer");
        assertThat(result.sources()).isNull();

        verify(embeddingProviderValidator).validate(DEFAULT_PROVIDER, ACTIVE_EMBEDDING);
        verify(historyService).saveHistory(DEFAULT_USER_ID, "ProcessedPrompt", "Expected answer");
        verify(semanticMemoryExtractor).extract(DEFAULT_USER_ID, DEFAULT_PROMPT, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);
        verifyNoInteractions(s3PresignedUrlService);
    }

    @Test
    void prompt_WhenEmbeddingProviderNotProvided_ThenResolvesFromPropertiesAndExecutes() {
        ProviderConfig config = new ProviderConfig();
        config.setDefaultEmbedding(ACTIVE_EMBEDDING);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(DEFAULT_PROVIDER, config));

        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("System...", ""));
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("ProcessedPrompt", List.of(), true));

        List<Message> mockHistory = List.of();
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(mockHistory);

        AiResponse mockResponse = new AiResponse("Answer", new CustomMetadata(null, List.of()));
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("ProcessedPrompt"), eq(mockHistory), eq((MultipartFile) null), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(mockResponse);

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID, DEFAULT_PROVIDER, DEFAULT_MODEL, null);

        assertThat(result.content()).isEqualTo("Answer");
        verify(embeddingProviderValidator).validate(DEFAULT_PROVIDER, ACTIVE_EMBEDDING);
        verify(semanticMemoryExtractor).extract(DEFAULT_USER_ID, DEFAULT_PROMPT, DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING);
    }

    @Test
    void prompt_WhenAttachSourcesFalse_ThenNoSourcesField() {
        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("S", ""));
        SourceRef ref = new SourceRef("b", "k.pdf", "k.pdf", "application/pdf");
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("U", List.of(ref), true));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(List.of());
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("U"), eq(List.of()), eq((MultipartFile) null), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(new AiResponse("Answer", new CustomMetadata(null, List.of())));

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID,
                DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING, false);

        assertThat(result.sources()).isNull();
        verify(s3PresignedUrlService, never()).presignAll(anyList());
    }

    @Test
    void prompt_WhenAttachSourcesTrue_AndRagRan_AndChunksRetrieved_ThenAttachesPresignedSources() {
        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("S", ""));
        SourceRef refA = new SourceRef("b", "a.pdf", "a.pdf", "application/pdf");
        SourceRef refB = new SourceRef("b", "b.md", "b.md", "text/markdown");
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("U", List.of(refA, refB), true));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(List.of());
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("U"), eq(List.of()), eq((MultipartFile) null), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(new AiResponse("Answer", new CustomMetadata(null, List.of())));

        SourceFile fileA = new SourceFile("a.pdf", "application/pdf", "https://m/a", Instant.now(), 1024L);
        SourceFile fileB = new SourceFile("b.md", "text/markdown", "https://m/b", Instant.now(), 512L);
        when(s3PresignedUrlService.presignAll(List.of(refA, refB))).thenReturn(List.of(fileA, fileB));

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID,
                DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING, true);

        assertThat(result.sources()).containsExactly(fileA, fileB);
    }

    @Test
    void prompt_WhenAttachSourcesTrue_AndRagRan_AndZeroChunks_ThenEmptySourcesArray() {
        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("S", ""));
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("U", List.of(), true));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(List.of());
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("U"), eq(List.of()), eq((MultipartFile) null), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(new AiResponse("Answer", new CustomMetadata(null, List.of())));
        when(s3PresignedUrlService.presignAll(List.of())).thenReturn(List.of());

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID,
                DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING, true);

        assertThat(result.sources()).isNotNull().isEmpty();
    }

    @Test
    void prompt_WhenAttachSourcesTrue_ButRagSkipped_ThenEmptySourcesArrayWithoutPresigning() {
        when(contextAssembler.buildSystemMessages(DEFAULT_USER_ID, DEFAULT_PROMPT, ACTIVE_EMBEDDING))
                .thenReturn(new AssembledSystemMessages("S", ""));
        when(contextAssembler.buildUserMessage(DEFAULT_PROMPT, null, ACTIVE_EMBEDDING))
                .thenReturn(new BuiltUserMessage("U", List.of(), false));
        when(historyService.loadHistory(DEFAULT_USER_ID)).thenReturn(List.of());
        when(chatExecutor.execute(eq(DEFAULT_USER_ID), ArgumentMatchers.<AssembledSystemMessages>any(),
                eq("U"), eq(List.of()), eq((MultipartFile) null), eq(DEFAULT_PROVIDER), eq(DEFAULT_MODEL)))
                .thenReturn(new AiResponse("Answer", new CustomMetadata(null, List.of())));

        AiResponse result = ascendChatService.prompt(DEFAULT_PROMPT, null, null, DEFAULT_USER_ID,
                DEFAULT_PROVIDER, DEFAULT_MODEL, ACTIVE_EMBEDDING, true);

        assertThat(result.sources()).isNotNull().isEmpty();
        verify(s3PresignedUrlService, never()).presignAll(anyList());
    }
}
