package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryClient;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryItem;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatContextAssemblerTest {

    private static final String DEFAULT_USER_ID = "user1";
    private static final String DEFAULT_USER_PROMPT = "How do I build this?";
    private static final String DEFAULT_EMBEDDING_PROVIDER = "openai";
    private static final String SYSTEM_PROMPT = "You are an AI assistant.";

    @Mock
    private UserInstructionService userInstructionService;

    @Mock
    private SemanticMemoryClient semanticMemoryClient;

    @Mock
    private SemanticMemoryProperties semanticMemoryProperties;

    @Mock
    private RagRetrievalService ragRetrievalService;

    @Mock
    private DocumentIngestionService documentIngestionService;

    @InjectMocks
    private ChatContextAssembler assembler;

    @BeforeEach
    void setupGlobalFields() {
        ReflectionTestUtils.setField(assembler, "baseSystemPrompt", SYSTEM_PROMPT);
    }

    @Test
    @DisplayName("buildSystemMessage assembles base prompt, user instructions, and memory items")
    void buildSystemMessage_WhenMemoryAndInstructionsExist_ThenAssemblesCorrectly() {
        // given
        when(userInstructionService.getInstructions(DEFAULT_USER_ID)).thenReturn("Be concise.");
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(10);

        SemanticMemoryItem item = createMemoryItem("User uses Java");
        when(semanticMemoryClient.search(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, 10, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(List.of(item));

        // when
        String result = assembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result)
                .contains(SYSTEM_PROMPT)
                .contains("User Instructions:\nBe concise.")
                .contains("User memory (may be relevant):\n- User uses Java");
    }

    @Test
    @DisplayName("buildSystemMessage assembles only the base prompt when memory and instructions are empty")
    void buildSystemMessage_WhenMemoryAndInstructionsEmpty_ThenAssemblesOnlyBasePrompt() {
        // given
        when(userInstructionService.getInstructions(DEFAULT_USER_ID)).thenReturn(null);
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(10);
        when(semanticMemoryClient.search(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, 10, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(List.of());

        // when
        String result = assembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result)
                .contains(SYSTEM_PROMPT)
                .contains("User Instructions:\n")
                .doesNotContain("User memory (may be relevant):");
    }

    @Test
    @DisplayName("buildSystemMessage gracefully ignores exceptions from semantic memory search")
    void buildSystemMessage_WhenSemanticMemoryThrowsException_ThenGracefullyIgnores() {
        // given
        when(userInstructionService.getInstructions(DEFAULT_USER_ID)).thenReturn("Be concise.");
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(10);
        when(semanticMemoryClient.search(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, 10, DEFAULT_EMBEDDING_PROVIDER))
                .thenThrow(new RuntimeException("Connection failed"));

        // when
        String result = assembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result)
                .contains(SYSTEM_PROMPT)
                .contains("User Instructions:\nBe concise.")
                .doesNotContain("User memory (may be relevant):");
    }

    @Test
    @DisplayName("buildUserMessage returns the original prompt unchanged when no document and no RAG results")
    void buildUserMessage_WhenNoDocAndNoRag_ThenReturnsOriginalPrompt() {
        // given
        when(ragRetrievalService.retrieve(DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(RagRetrievalResult.empty());

        // when
        BuiltUserMessage result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result.text()).isEqualTo(DEFAULT_USER_PROMPT);
        assertThat(result.sources()).isEmpty();
        assertThat(result.ragRetrievalRan()).isTrue();
    }

    @Test
    @DisplayName("buildUserMessage appends document content and RAG context and propagates source refs")
    void buildUserMessage_WhenDocAndRagExist_ThenAppendsBothAndPropagatesSources() {
        // given
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(false);
        when(documentIngestionService.processDocument(document)).thenReturn("\n[Doc Content]");

        String intermediatePrompt = DEFAULT_USER_PROMPT + "\n[Doc Content]";
        SourceRef ref = new SourceRef("bucket", "manual.pdf", "manual.pdf", "application/pdf");
        when(ragRetrievalService.retrieve(intermediatePrompt, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(new RagRetrievalResult("[RAG Content]", List.of(ref), true));

        // when
        BuiltUserMessage result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, document, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result.text())
                .contains(DEFAULT_USER_PROMPT)
                .contains("[Doc Content]")
                .contains("[RAG Content]");
        assertThat(result.sources()).containsExactly(ref);
        assertThat(result.ragRetrievalRan()).isTrue();
    }

    @Test
    @DisplayName("buildUserMessage ignores an empty document attachment")
    void buildUserMessage_WhenEmptyDocAndNoRag_ThenIgnoresDocument() {
        // given
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(true);
        when(ragRetrievalService.retrieve(DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(RagRetrievalResult.empty());

        // when
        BuiltUserMessage result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, document, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result.text()).isEqualTo(DEFAULT_USER_PROMPT);
        assertThat(result.sources()).isEmpty();
    }

    @Test
    @DisplayName("buildUserMessage returns ragRetrievalRan=false when RAG retrieval was skipped")
    void buildUserMessage_WhenRagDisabled_ThenRagRetrievalRanIsFalse() {
        // given
        when(ragRetrievalService.retrieve(DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(RagRetrievalResult.skipped());

        // when
        BuiltUserMessage result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result.text()).isEqualTo(DEFAULT_USER_PROMPT);
        assertThat(result.ragRetrievalRan()).isFalse();
    }

    @Test
    @DisplayName("buildSystemMessage includes a Python-related memory fact in the assembled message")
    void buildSystemMessage_WhenMemoryContainsPythonFact_ThenIncludesPythonFactInMessage() {
        // given
        when(userInstructionService.getInstructions(DEFAULT_USER_ID)).thenReturn(null);
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(10);

        SemanticMemoryItem item = createMemoryItem("User uses Python");
        when(semanticMemoryClient.search(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, 10, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(List.of(item));

        // when
        String result = assembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result).contains("User uses Python");
    }

    @Test
    @DisplayName("buildSystemMessage includes all multiple memory facts in the assembled message")
    void buildSystemMessage_WhenMemoryContainsMultipleFacts_ThenAllFactsIncluded() {
        // given
        when(userInstructionService.getInstructions(DEFAULT_USER_ID)).thenReturn(null);
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(10);

        SemanticMemoryItem item1 = createMemoryItem("User prefers dark mode");
        SemanticMemoryItem item2 = createMemoryItem("User works in fintech");
        when(semanticMemoryClient.search(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, 10, DEFAULT_EMBEDDING_PROVIDER))
                .thenReturn(List.of(item1, item2));

        // when
        String result = assembler.buildSystemMessage(DEFAULT_USER_ID, DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result)
                .contains("User prefers dark mode")
                .contains("User works in fintech");
    }

    private SemanticMemoryItem createMemoryItem(String text) {
        return new SemanticMemoryItem("id1", "user1", text, 0.9d, Instant.now(), Map.of());
    }
}