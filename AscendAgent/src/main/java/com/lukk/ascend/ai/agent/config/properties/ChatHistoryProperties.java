package com.lukk.ascend.ai.agent.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@ConfigurationProperties(prefix = "app.memory.chat-history")
public class ChatHistoryProperties {

    private int maxSize = 5;

    private Duration ttl = Duration.ofHours(24);

    private Redis redis = new Redis();

    private Postgres postgres = new Postgres();

    public int getMaxSize() {
        return maxSize;
    }

    public void setMaxSize(int maxSize) {
        this.maxSize = maxSize;
    }

    public Duration getTtl() {
        return ttl;
    }

    public void setTtl(Duration ttl) {
        this.ttl = ttl;
    }

    public Redis getRedis() {
        return redis;
    }

    public void setRedis(Redis redis) {
        this.redis = redis;
    }

    public Postgres getPostgres() {
        return postgres;
    }

    public void setPostgres(Postgres postgres) {
        this.postgres = postgres;
    }

    public static class Redis {

        private boolean enabled = true;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }
    }

    public static class Postgres {

        private boolean enabled = true;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }
    }
}
