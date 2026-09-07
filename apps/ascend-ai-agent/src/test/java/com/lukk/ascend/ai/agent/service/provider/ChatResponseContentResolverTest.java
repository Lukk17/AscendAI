package com.lukk.ascend.ai.agent.service.provider;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class ChatResponseContentResolverTest {

    private static final String THINKING_TEXT = "Let me analyze this request step by step...";
    private static final String ACTUAL_ANSWER = "Hello! How can I help you today?";

    @InjectMocks
    private ChatResponseContentResolver resolver;

    @Test
    @DisplayName("resolveContent returns the text of a single generation")
    void resolveContent_WhenSingleGeneration_ThenReturnsThatText() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    @DisplayName("resolveContent returns the last generation text when a thinking model produces two generations")
    void resolveContent_WhenThinkingModelWithTwoGenerations_ThenReturnsLastGeneration() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(THINKING_TEXT, ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    @DisplayName("resolveContent skips blank intermediate generations and returns the last non-blank one")
    void resolveContent_WhenMultipleGenerationsWithBlankIntermediate_ThenReturnsLastNonBlank() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(THINKING_TEXT, "", ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    @DisplayName("resolveContent returns empty string when the ChatResponse is null")
    void resolveContent_WhenNullResponse_ThenReturnsEmptyString() {
        // given / when
        String result = resolver.resolveContent(null);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("resolveContent returns empty string when the generations list is empty")
    void resolveContent_WhenEmptyGenerationsList_ThenReturnsEmptyString() {
        // given
        ChatResponse chatResponse = new ChatResponse(List.of());

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("resolveContent returns empty string when all generations are blank")
    void resolveContent_WhenAllGenerationsBlank_ThenReturnsEmptyString() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of("", "   ", ""));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("resolveContent returns the last non-blank generation when the final one is blank")
    void resolveContent_WhenLastGenerationBlankButPreviousHasText_ThenReturnsPreviousText() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(THINKING_TEXT, ACTUAL_ANSWER, ""));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    private ChatResponse createChatResponse(List<String> texts) {
        List<Generation> generations = texts.stream()
                .map(text -> new Generation(new AssistantMessage(text)))
                .toList();
        return new ChatResponse(generations);
    }
}
