package com.lukk.ascend.ai.agent.service;

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
    void resolveContent_WhenSingleGeneration_ThenReturnsThatText() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    void resolveContent_WhenThinkingModelWithTwoGenerations_ThenReturnsLastGeneration() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(THINKING_TEXT, ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    void resolveContent_WhenMultipleGenerationsWithBlankIntermediate_ThenReturnsLastNonBlank() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of(THINKING_TEXT, "", ACTUAL_ANSWER));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEqualTo(ACTUAL_ANSWER);
    }

    @Test
    void resolveContent_WhenNullResponse_ThenReturnsEmptyString() {
        // given / when
        String result = resolver.resolveContent(null);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void resolveContent_WhenEmptyGenerationsList_ThenReturnsEmptyString() {
        // given
        ChatResponse chatResponse = new ChatResponse(List.of());

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void resolveContent_WhenAllGenerationsBlank_ThenReturnsEmptyString() {
        // given
        ChatResponse chatResponse = createChatResponse(List.of("", "   ", ""));

        // when
        String result = resolver.resolveContent(chatResponse);

        // then
        assertThat(result).isEmpty();
    }

    @Test
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
