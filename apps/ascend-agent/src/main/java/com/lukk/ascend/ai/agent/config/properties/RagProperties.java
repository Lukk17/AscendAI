package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.unit.DataSize;

import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.rag")
public class RagProperties {

    private boolean enabled = true;

    private int topK = 5;

    private double similarityThreshold = 0.4;

    private int maxContextChars = 4000;

    private SourceAttachments sourceAttachments = new SourceAttachments();

    @Getter
    @Setter
    public static class SourceAttachments {

        private boolean enabled = true;

        private Duration presignTtl = Duration.ofMinutes(15);

        private DataSize maxFileSize = DataSize.ofMegabytes(25);
    }
}
