package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.security")
public class SecurityProperties {

    private boolean enabled = false;

    private User user = new User();

    @Getter
    @Setter
    public static class User {

        private String username = "admin";

        private String password = "admin";
    }
}
