package com.lukk.ascend.ai.agent.service.provider;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.ToolCallingChatOptions;
import org.springframework.ai.model.tool.ToolCallingManager;
import org.springframework.ai.model.tool.ToolExecutionResult;
import org.springframework.ai.tool.definition.ToolDefinition;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class TrackingToolCallingManagerTest {

    @Mock
    private ToolCallingManager delegate;

    private final ToolCallTracker toolCallTracker = new ToolCallTracker();

    private TrackingToolCallingManager trackingToolCallingManager;

    @Test
    @DisplayName("executeToolCalls records the requested tool names before delegating")
    void executeToolCalls_WhenToolCallsRequested_ThenRecordsNamesAndDelegates() {
        // given
        trackingToolCallingManager = new TrackingToolCallingManager(delegate, toolCallTracker);
        Prompt prompt = mock(Prompt.class);
        ChatResponse chatResponse = chatResponseWithToolCalls("weather_current", "weather_forecast");
        ToolExecutionResult expected = mock(ToolExecutionResult.class);
        when(delegate.executeToolCalls(prompt, chatResponse)).thenReturn(expected);

        // when
        ToolExecutionResult result = trackingToolCallingManager.executeToolCalls(prompt, chatResponse);

        // then
        assertThat(result).isSameAs(expected);
        assertThat(toolCallTracker.drain()).containsExactly("weather_current", "weather_forecast");
        verify(delegate).executeToolCalls(prompt, chatResponse);
    }

    @Test
    @DisplayName("executeToolCalls records nothing when a generation carries no tool calls")
    void executeToolCalls_WhenNoToolCallsPresent_ThenRecordsNothing() {
        // given
        trackingToolCallingManager = new TrackingToolCallingManager(delegate, toolCallTracker);
        Prompt prompt = mock(Prompt.class);
        ChatResponse chatResponse = chatResponseWithToolCalls();
        when(delegate.executeToolCalls(prompt, chatResponse)).thenReturn(mock(ToolExecutionResult.class));

        // when
        trackingToolCallingManager.executeToolCalls(prompt, chatResponse);

        // then
        assertThat(toolCallTracker.drain()).isEmpty();
    }

    @Test
    @DisplayName("resolveToolDefinitions delegates to the wrapped manager")
    void resolveToolDefinitions_WhenCalled_ThenDelegates() {
        // given
        trackingToolCallingManager = new TrackingToolCallingManager(delegate, toolCallTracker);
        ToolCallingChatOptions options = mock(ToolCallingChatOptions.class);
        List<ToolDefinition> expected = List.of(mock(ToolDefinition.class));
        when(delegate.resolveToolDefinitions(any())).thenReturn(expected);

        // when
        List<ToolDefinition> result = trackingToolCallingManager.resolveToolDefinitions(options);

        // then
        assertThat(result).isSameAs(expected);
        verify(delegate).resolveToolDefinitions(options);
    }

    private ChatResponse chatResponseWithToolCalls(String... toolNames) {
        AssistantMessage assistantMessage = mock(AssistantMessage.class);
        List<AssistantMessage.ToolCall> toolCalls = List.of(toolNames).stream()
                .map(name -> new AssistantMessage.ToolCall(name, name, name, "{}"))
                .toList();
        when(assistantMessage.getToolCalls()).thenReturn(toolCalls);

        Generation generation = mock(Generation.class);
        when(generation.getOutput()).thenReturn(assistantMessage);

        ChatResponse chatResponse = mock(ChatResponse.class);
        when(chatResponse.getResults()).thenReturn(List.of(generation));

        return chatResponse;
    }
}
