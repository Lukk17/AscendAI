package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.HashMap;
import java.util.Map;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.ai.prompt-cache")
public class PromptCacheProperties {

    private boolean enabled = true;

    private Map<String, ProviderCache> providers = new HashMap<>();

    public boolean isProviderEnabled(String providerName) {
        if (!enabled) {
            return false;
        }

        ProviderCache pc = providers.get(providerName);

        return pc == null || pc.isEnabled();
    }

    @Getter
    @Setter
    public static class ProviderCache {

        private boolean enabled = true;
    }
}
