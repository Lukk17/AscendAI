package com.lukk.ascend.ai.agent.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Map;

@ConfigurationProperties(prefix = "app.memory.chat-history.compaction")
public class ChatHistoryCompactionProperties {

    private boolean enabled = true;

    private int turnTrigger = 20;

    private double tokenTriggerFraction = 0.5;

    private int keepRecentTurns = 8;

    private int maxSummaryTokens = 800;

    private Map<String, String> providerDefaults = new LinkedHashMap<>();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public int getTurnTrigger() {
        return turnTrigger;
    }

    public void setTurnTrigger(int turnTrigger) {
        this.turnTrigger = turnTrigger;
    }

    public double getTokenTriggerFraction() {
        return tokenTriggerFraction;
    }

    public void setTokenTriggerFraction(double tokenTriggerFraction) {
        this.tokenTriggerFraction = tokenTriggerFraction;
    }

    public int getKeepRecentTurns() {
        return keepRecentTurns;
    }

    public void setKeepRecentTurns(int keepRecentTurns) {
        this.keepRecentTurns = keepRecentTurns;
    }

    public int getMaxSummaryTokens() {
        return maxSummaryTokens;
    }

    public void setMaxSummaryTokens(int maxSummaryTokens) {
        this.maxSummaryTokens = maxSummaryTokens;
    }

    public Map<String, String> getProviderDefaults() {
        return providerDefaults;
    }

    public void setProviderDefaults(Map<String, String> providerDefaults) {
        this.providerDefaults = providerDefaults;
    }
}
