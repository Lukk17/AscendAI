package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.test.BaseIntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.web.SecurityFilterChain;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Covers the {@code securityEnabled=true} branch in {@link SecurityConfig#securityFilterChain}.
 * Boots a lightweight Spring context with security flipped on so JaCoCo instruments the
 * {@code if (securityEnabled)} true-branch in the filter chain factory method.
 */
@SpringBootTest(properties = {
        "app.security.enabled=true",
        "spring.datasource.url=jdbc:h2:mem:testdb",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect",
        "spring.integration.jdbc.initialize-schema=always",
        "spring.ai.mcp.client.enabled=false"
})
class SecurityConfigEnabledBranchIT extends BaseIntegrationTest {

    @Autowired
    private SecurityFilterChain securityFilterChain;

    @Test
    @DisplayName("securityFilterChain bean is created when securityEnabled=true (covers the if-true branch)")
    void securityFilterChain_SecurityEnabled_BeanCreated() {
        assertThat(securityFilterChain).isNotNull();
    }
}
