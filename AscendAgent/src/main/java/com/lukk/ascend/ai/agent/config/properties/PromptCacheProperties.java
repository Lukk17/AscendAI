package com.lukk.ascend.ai.agent.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.HashMap;
import java.util.Map;

@ConfigurationProperties(prefix = "app.ai.prompt-cache")
public class PromptCacheProperties {

    private boolean enabled = true;

    private Map<String, ProviderCache> providers = new HashMap<>();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public Map<String, ProviderCache> getProviders() {
        return providers;
    }

    public void setProviders(Map<String, ProviderCache> providers) {
        this.providers = providers;
    }

    public boolean isProviderEnabled(String providerName) {
        if (!enabled) {
            return false;
        }
        ProviderCache pc = providers.get(providerName);
        return pc == null || pc.isEnabled();
    }

    public static class ProviderCache {

        private boolean enabled = true;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }
    }
}
