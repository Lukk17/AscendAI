package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.ascend-ocr")
public class AscendOcrProperties {

    private String baseUrl = "http://localhost:7022";

    private String apiPath = "/v1/ocr/jobs";

    private Duration pollMinInterval = Duration.ofSeconds(1);

    private Duration pollMaxInterval = Duration.ofSeconds(30);

    private Duration pollTimeout = Duration.ofMinutes(15);

    private int submitRetryAttempts = 3;

    private Duration submitRetryMaxDelay = Duration.ofSeconds(30);
}
