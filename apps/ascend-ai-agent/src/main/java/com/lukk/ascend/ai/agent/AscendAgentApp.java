package com.lukk.ascend.ai.agent;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class AscendAgentApp {

    public static void main(String[] args) {
        SpringApplication.run(AscendAgentApp.class, args);
    }

}
