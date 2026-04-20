package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.orchestrator.service.memory.SemanticMemoryClient;
import com.lukk.ascend.ai.orchestrator.service.memory.SemanticMemoryItem;
import org.junit.jupiter.api.BeforeEach;
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
    void buildUserMessage_WhenNoDocAndNoRag_ThenReturnsOriginalPrompt() {
        // given
        when(ragRetrievalService.retrieveContext(DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER)).thenReturn("");

        // when
        String result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEqualTo(DEFAULT_USER_PROMPT);
    }

    @Test
    void buildUserMessage_WhenDocAndRagExist_ThenAppendsBoth() {
        // given
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(false);
        when(documentIngestionService.processDocument(document)).thenReturn("\n[Doc Content]");

        String intermediatePrompt = DEFAULT_USER_PROMPT + "\n[Doc Content]";
        when(ragRetrievalService.retrieveContext(intermediatePrompt, DEFAULT_EMBEDDING_PROVIDER)).thenReturn("[RAG Content]");

        // when
        String result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, document, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result)
                .contains(DEFAULT_USER_PROMPT)
                .contains("[Doc Content]")
                .contains("[RAG Content]");
    }

    @Test
    void buildUserMessage_WhenEmptyDocAndNoRag_ThenIgnoresDocument() {
        // given
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(true);
        when(ragRetrievalService.retrieveContext(DEFAULT_USER_PROMPT, DEFAULT_EMBEDDING_PROVIDER)).thenReturn("");

        // when
        String result = assembler.buildUserMessage(DEFAULT_USER_PROMPT, document, DEFAULT_EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEqualTo(DEFAULT_USER_PROMPT);
    }

    private SemanticMemoryItem createMemoryItem(String text) {
        return new SemanticMemoryItem("id1", "user1", text, 0.9d, Instant.now(), Map.of());
    }
}