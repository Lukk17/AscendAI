package com.lukk.ascend.ai.agent.config;

import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.assertj.core.api.Assertions.assertThat;

class SecurityConfigTest {

    @Test
    void passwordEncoder_BCryptStrategy_HashesAndMatches() {
        SecurityConfig config = new SecurityConfig();

        PasswordEncoder encoder = config.passwordEncoder();
        String hash = encoder.encode("admin");

        assertThat(hash).isNotEqualTo("admin");
        assertThat(encoder.matches("admin", hash)).isTrue();
        assertThat(encoder.matches("wrong", hash)).isFalse();
    }

    @Test
    void userDetailsService_CreatesUserFromConfiguredCredentials() {
        SecurityConfig config = new SecurityConfig();
        org.springframework.test.util.ReflectionTestUtils.setField(config, "username", "alice");
        org.springframework.test.util.ReflectionTestUtils.setField(config, "password", "wonderland");

        var encoder = config.passwordEncoder();
        var uds = config.userDetailsService(encoder);
        var user = uds.loadUserByUsername("alice");

        assertThat(user.getUsername()).isEqualTo("alice");
        assertThat(encoder.matches("wonderland", user.getPassword())).isTrue();
        assertThat(user.getAuthorities()).extracting("authority").contains("ROLE_USER");
    }
}
