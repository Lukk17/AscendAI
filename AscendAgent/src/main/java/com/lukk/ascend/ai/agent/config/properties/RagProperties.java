package com.lukk.ascend.ai.agent.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.unit.DataSize;

import java.time.Duration;

@ConfigurationProperties(prefix = "app.rag")
public class RagProperties {

    private boolean enabled = true;

    private int topK = 5;

    private double similarityThreshold = 0.4;

    private int maxContextChars = 4000;

    private SourceAttachments sourceAttachments = new SourceAttachments();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public int getTopK() {
        return topK;
    }

    public void setTopK(int topK) {
        this.topK = topK;
    }

    public double getSimilarityThreshold() {
        return similarityThreshold;
    }

    public void setSimilarityThreshold(double similarityThreshold) {
        this.similarityThreshold = similarityThreshold;
    }

    public int getMaxContextChars() {
        return maxContextChars;
    }

    public void setMaxContextChars(int maxContextChars) {
        this.maxContextChars = maxContextChars;
    }

    public SourceAttachments getSourceAttachments() {
        return sourceAttachments;
    }

    public void setSourceAttachments(SourceAttachments sourceAttachments) {
        this.sourceAttachments = sourceAttachments;
    }

    public static class SourceAttachments {

        private boolean enabled = true;

        private Duration presignTtl = Duration.ofMinutes(15);

        private DataSize maxFileSize = DataSize.ofMegabytes(25);

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public Duration getPresignTtl() {
            return presignTtl;
        }

        public void setPresignTtl(Duration presignTtl) {
            this.presignTtl = presignTtl;
        }

        public DataSize getMaxFileSize() {
            return maxFileSize;
        }

        public void setMaxFileSize(DataSize maxFileSize) {
            this.maxFileSize = maxFileSize;
        }
    }
}
