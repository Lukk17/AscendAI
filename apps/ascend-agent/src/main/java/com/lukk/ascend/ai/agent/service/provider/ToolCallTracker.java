package com.lukk.ascend.ai.agent.service.provider;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
public class ToolCallTracker {

    private final ThreadLocal<List<String>> executedToolNames = ThreadLocal.withInitial(ArrayList::new);

    public void reset() {
        executedToolNames.remove();
    }

    public void record(String toolName) {
        executedToolNames.get().add(toolName);
    }

    public List<String> drain() {
        List<String> names = executedToolNames.get().stream().distinct().toList();
        executedToolNames.remove();
        return names;
    }
}
