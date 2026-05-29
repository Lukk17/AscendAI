package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryClient;
import com.lukk.ascend.ai.agent.service.memory.SemanticMemoryItem;
import com.lukk.ascend.ai.agent.service.rag.BuiltUserMessage;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for ChatContextAssembler:
 *  - null memory items filtered from semantic memory block
 *  - memory item with blank text filtered
 *  - lines list empty after filtering -> returns ""
 *  - RAG context not appended when retrieval.context() is blank but not empty
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ChatContextAssemblerExtraTest {

    private static final String USER_ID = "frosty";
    private static final String USER_PROMPT = "what do you know about me?";
    private static final String EMBED_PROVIDER = "lmstudio";
    private static final String SYSTEM_PROMPT = "You are a helpful assistant.";

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
    void setUp() {
        ReflectionTestUtils.setField(assembler, "baseSystemPrompt", SYSTEM_PROMPT);
        when(semanticMemoryProperties.getSearchLimit()).thenReturn(5);
        when(userInstructionService.getInstructions(USER_ID)).thenReturn(null);
    }

    @Test
    @DisplayName("buildSystemMessages skips null SemanticMemoryItem entries in the memory block")
    void buildSystemMessages_NullMemoryItems_SkipsNulls() {
        // given — list has one null and one real item
        SemanticMemoryItem real = new SemanticMemoryItem("id1", USER_ID, "User likes Java", 0.9, Instant.now(), Map.of());
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER))
                .thenReturn(Arrays.asList(null, real));

        // when
        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        // then — null item skipped, real item included
        assertThat(result).contains("User likes Java");
    }

    @Test
    @DisplayName("buildSystemMessages skips memory items with null text")
    void buildSystemMessages_ItemWithNullText_Skipped() {
        // given
        SemanticMemoryItem nullText = new SemanticMemoryItem("id1", USER_ID, null, 0.9, Instant.now(), Map.of());
        SemanticMemoryItem valid = new SemanticMemoryItem("id2", USER_ID, "User uses Python", 0.8, Instant.now(), Map.of());
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER))
                .thenReturn(List.of(nullText, valid));

        // when
        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        // then
        assertThat(result).contains("User uses Python");
        assertThat(result).doesNotContain("null");
    }

    @Test
    @DisplayName("buildSystemMessages skips memory items with blank text")
    void buildSystemMessages_ItemWithBlankText_Skipped() {
        // given
        SemanticMemoryItem blank = new SemanticMemoryItem("id1", USER_ID, "   ", 0.9, Instant.now(), Map.of());
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER))
                .thenReturn(List.of(blank));

        // when
        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        // then — no memory block since all items filtered
        assertThat(result).doesNotContain("User memory (may be relevant):");
    }

    @Test
    @DisplayName("buildSystemMessages produces no memory block when all items have blank text")
    void buildSystemMessages_AllItemsBlankText_ProducesNoMemoryBlock() {
        // given — only items with blank texts
        SemanticMemoryItem b1 = new SemanticMemoryItem("id1", USER_ID, "", 0.9, Instant.now(), Map.of());
        SemanticMemoryItem b2 = new SemanticMemoryItem("id2", USER_ID, "  ", 0.8, Instant.now(), Map.of());
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER))
                .thenReturn(List.of(b1, b2));

        // when
        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        // then
        assertThat(result).doesNotContain("User memory (may be relevant):");
    }

    @Test
    @DisplayName("buildSystemMessages null items list returns no memory block")
    void buildSystemMessages_NullItemsList_ReturnsNoMemoryBlock() {
        // This exercises items == null path in buildSemanticMemoryBlock
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER)).thenReturn(null);

        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        assertThat(result).doesNotContain("User memory (may be relevant):");
    }

    @Test
    @DisplayName("buildSystemMessages with non-blank instructions logs YES state")
    void buildSystemMessages_NonBlankInstructions_LogsYesState() {
        // The log statement at line 47: instructions != null && !instructions.isBlank() ? "YES" : "NO"
        when(userInstructionService.getInstructions(USER_ID)).thenReturn("Be precise.");
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER)).thenReturn(List.of());

        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        assertThat(result).contains("Be precise.");
    }

    @Test
    @DisplayName("buildSystemMessages logs NO for instructions when instructions is blank (not null)")
    void buildSystemMessages_BlankInstructions_LogsNoState() {
        // instructions != null && !instructions.isBlank() = true && false = false -> "NO" in log
        when(userInstructionService.getInstructions(USER_ID)).thenReturn("   "); // blank, not null
        when(semanticMemoryClient.search(USER_ID, USER_PROMPT, 5, EMBED_PROVIDER)).thenReturn(List.of());

        String result = assembler.buildSystemMessage(USER_ID, USER_PROMPT, EMBED_PROVIDER);

        // Still builds the system message, log says NO for instructions
        assertThat(result).contains(SYSTEM_PROMPT);
    }

    @Test
    @DisplayName("buildUserMessage does not append context when RAG context is blank string")
    void buildUserMessage_RagContextBlank_DoesNotAppend() {
        // given — context is empty string (blank) so !context.isBlank() is false
        when(ragRetrievalService.retrieve(USER_PROMPT, EMBED_PROVIDER))
                .thenReturn(new RagRetrievalResult("", List.of(), true));

        // when
        BuiltUserMessage result = assembler.buildUserMessage(USER_PROMPT, null, EMBED_PROVIDER);

        // then
        assertThat(result.text()).isEqualTo(USER_PROMPT);
    }
}
