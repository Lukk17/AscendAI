package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Map;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.memory.chat-history.compaction")
public class ChatHistoryCompactionProperties {

    private boolean enabled = true;

    private int turnTrigger = 20;

    private double tokenTriggerFraction = 0.5;

    private int keepRecentTurns = 8;

    private int maxSummaryTokens = 800;

    private Map<String, String> providerDefaults = new LinkedHashMap<>();
}
