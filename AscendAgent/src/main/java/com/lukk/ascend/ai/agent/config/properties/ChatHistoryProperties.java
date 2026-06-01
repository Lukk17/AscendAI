package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.memory.chat-history")
public class ChatHistoryProperties {

    private int maxSize = 5;

    private Duration ttl = Duration.ofHours(24);

    private Redis redis = new Redis();

    private Postgres postgres = new Postgres();

    @Getter
    @Setter
    public static class Redis {

        private boolean enabled = true;
    }

    @Getter
    @Setter
    public static class Postgres {

        private boolean enabled = true;
    }
}
