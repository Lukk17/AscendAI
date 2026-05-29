package com.lukk.ascend.ai.agent.service.chat;
import com.lukk.ascend.ai.agent.service.provider.EmbeddingProviderValidator;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.memory.CompactionOverride;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryExtractor;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.S3PresignedUrlService;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AscendChatServiceSourceAttachmentsTest {

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

    @BeforeEach
    void setUp() {
        when(aiProviderProperties.getDefaultProvider()).thenReturn("openai");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of());

        when(contextAssembler.buildSystemMessages(anyString(), anyString(), any()))
                .thenReturn(new AssembledSystemMessages("sys", ""));
        when(historyService.loadHistory(anyString())).thenReturn(List.of());
        when(chatExecutor.execute(anyString(), any(AssembledSystemMessages.class), anyString(),
                any(), any(), any(), any()))
                .thenReturn(new AiResponse("reply", null));
    }

    @Test
    @DisplayName("prompt attaches presigned sources when attachSources=true and ragRetrievalRan=true")
    void prompt_AttachSourcesTrueAndRagRan_AttachesPresignedSources() {
        // given
        SourceRef ref = new SourceRef("bucket", "key.pdf", "key.pdf", "application/pdf");
        BuiltUserMessage userMessage = new BuiltUserMessage("prompt text", List.of(ref), true);
        when(contextAssembler.buildUserMessage(anyString(), any(), any())).thenReturn(userMessage);
        when(s3PresignedUrlService.presignAll(any()))
                .thenReturn(List.of(new com.lukk.ascend.ai.agent.dto.SourceFile("key.pdf", "application/pdf",
                        "https://example.com/key.pdf", java.time.Instant.now(), 1024L)));

        // when
        AiResponse response = ascendChatService.prompt("hello", null, null, TestConstants.DEFAULT_USER_ID,
                "openai", null, "openai", true, CompactionOverride.EMPTY);

        // then
        assertThat(response.sources()).hasSize(1);
        verify(s3PresignedUrlService).presignAll(any());
    }

    @Test
    @DisplayName("prompt returns empty sources when attachSources=true but ragRetrievalRan=false")
    void prompt_AttachSourcesTrueButRagSkipped_ReturnsEmptySources() {
        // given
        BuiltUserMessage userMessage = new BuiltUserMessage("prompt text", List.of(), false);
        when(contextAssembler.buildUserMessage(anyString(), any(), any())).thenReturn(userMessage);

        // when
        AiResponse response = ascendChatService.prompt("hello", null, null, TestConstants.DEFAULT_USER_ID,
                "openai", null, "openai", true, CompactionOverride.EMPTY);

        // then
        assertThat(response.sources()).isEmpty();
    }

    @Test
    @DisplayName("prompt does not attach sources when attachSources=false")
    void prompt_AttachSourcesFalse_NoSourcesAttached() {
        // given
        BuiltUserMessage userMessage = new BuiltUserMessage("prompt text", List.of(), true);
        when(contextAssembler.buildUserMessage(anyString(), any(), any())).thenReturn(userMessage);

        // when
        AiResponse response = ascendChatService.prompt("hello", null, null, TestConstants.DEFAULT_USER_ID,
                "openai", null, "openai", false, CompactionOverride.EMPTY);

        // then
        assertThat(response.sources()).isNull();
    }

    @Test
    @DisplayName("prompt handles null compactionOverride by defaulting to EMPTY")
    void prompt_NullCompactionOverride_HandledGracefully() {
        // given
        BuiltUserMessage userMessage = new BuiltUserMessage("prompt text", List.of(), false);
        when(contextAssembler.buildUserMessage(anyString(), any(), any())).thenReturn(userMessage);

        // when — must not throw
        AiResponse response = ascendChatService.prompt("hello", null, null, TestConstants.DEFAULT_USER_ID,
                "openai", null, "openai", false, null);

        assertThat(response.content()).isEqualTo("reply");
    }

    @Test
    @DisplayName("prompt resolves embeddingProvider from provider config when null is passed")
    void prompt_NullEmbeddingProvider_ResolvedFromProviderConfig() {
        // given — provider has a defaultEmbedding configured
        AiProviderProperties.ProviderConfig config = new AiProviderProperties.ProviderConfig();
        config.setDefaultEmbedding("lmstudio");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("openai", config));

        BuiltUserMessage userMessage = new BuiltUserMessage("text", List.of(), false);
        when(contextAssembler.buildUserMessage(anyString(), any(), any())).thenReturn(userMessage);

        // when
        AiResponse response = ascendChatService.prompt("hello", null, null, TestConstants.DEFAULT_USER_ID,
                "openai", null, null, false, CompactionOverride.EMPTY);

        assertThat(response.content()).isEqualTo("reply");
    }
}
