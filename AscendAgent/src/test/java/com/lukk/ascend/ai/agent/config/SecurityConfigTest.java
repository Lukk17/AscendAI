package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.config.properties.SecurityProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.assertj.core.api.Assertions.assertThat;

class SecurityConfigTest {

    @Test
    @DisplayName("passwordEncoder hashes input and matches it back")
    void passwordEncoder_BCryptStrategy_HashesAndMatches() {
        // given
        SecurityConfig config = new SecurityConfig(new SecurityProperties());

        // when
        PasswordEncoder encoder = config.passwordEncoder();
        String hash = encoder.encode("admin");

        // then
        assertThat(hash).isNotEqualTo("admin");
        assertThat(encoder.matches("admin", hash)).isTrue();
        assertThat(encoder.matches("wrong", hash)).isFalse();
    }

    @Test
    @DisplayName("userDetailsService creates a single user from configured credentials")
    void userDetailsService_CreatesUserFromConfiguredCredentials() {
        // given
        SecurityProperties props = new SecurityProperties();
        props.getUser().setUsername("alice");
        props.getUser().setPassword("wonderland");
        SecurityConfig config = new SecurityConfig(props);

        // when
        PasswordEncoder encoder = config.passwordEncoder();
        UserDetailsService uds = config.userDetailsService(encoder);
        UserDetails user = uds.loadUserByUsername("alice");

        // then
        assertThat(user.getUsername()).isEqualTo("alice");
        assertThat(encoder.matches("wonderland", user.getPassword())).isTrue();
        assertThat(user.getAuthorities()).extracting("authority").contains("ROLE_USER");
    }

    @Test
    @DisplayName("userDetailsService still creates a user when securityEnabled is false (defaults applied)")
    void userDetailsService_SecurityDisabled_StillCreatesDefaultUser() {
        // given
        SecurityProperties props = new SecurityProperties();
        SecurityConfig config = new SecurityConfig(props);

        // when
        PasswordEncoder encoder = config.passwordEncoder();
        UserDetailsService uds = config.userDetailsService(encoder);

        // then
        assertThat(uds.loadUserByUsername("admin")).isNotNull();
    }
}
