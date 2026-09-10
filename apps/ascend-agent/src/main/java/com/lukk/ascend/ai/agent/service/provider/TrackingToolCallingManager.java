package com.lukk.ascend.ai.agent.service.provider;

import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.ToolCallingChatOptions;
import org.springframework.ai.model.tool.ToolCallingManager;
import org.springframework.ai.model.tool.ToolExecutionResult;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.util.CollectionUtils;

import java.util.List;

/**
 * Records the name of every tool Spring AI's internal tool-execution loop is about to run.
 */
class TrackingToolCallingManager implements ToolCallingManager {

    private final ToolCallingManager delegate;
    private final ToolCallTracker toolCallTracker;

    TrackingToolCallingManager(ToolCallingManager delegate, ToolCallTracker toolCallTracker) {
        this.delegate = delegate;
        this.toolCallTracker = toolCallTracker;
    }

    @Override
    public List<ToolDefinition> resolveToolDefinitions(ToolCallingChatOptions chatOptions) {
        return delegate.resolveToolDefinitions(chatOptions);
    }

    @Override
    public ToolExecutionResult executeToolCalls(Prompt prompt, ChatResponse chatResponse) {
        recordRequestedToolCalls(chatResponse);
        return delegate.executeToolCalls(prompt, chatResponse);
    }

    private void recordRequestedToolCalls(ChatResponse chatResponse) {
        chatResponse.getResults().stream()
                .map(Generation::getOutput)
                .map(AssistantMessage::getToolCalls)
                .filter(toolCalls -> !CollectionUtils.isEmpty(toolCalls))
                .flatMap(List::stream)
                .map(AssistantMessage.ToolCall::name)
                .forEach(toolCallTracker::record);
    }
}
