package com.lukk.ascend.ai.agent.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;

/**
 * AscendAgent HTTP security.
 *
 * <p>Disabled by default ({@code app.security.enabled=false}) so local dev and
 * the existing test/Bruno workflow keep working without auth headers. Flip the
 * flag in production to enable HTTP Basic against an in-memory user defined by
 * {@code app.security.user.username} / {@code app.security.user.password}.
 *
 * <p>For real deployments swap the in-memory user manager for an OAuth2
 * resource-server, JWT, or Keycloak adapter — that's a separate change.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Value("${app.security.enabled:false}")
    private boolean securityEnabled;

    @Value("${app.security.user.username:admin}")
    private String username;

    @Value("${app.security.user.password:admin}")
    private String password;

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public UserDetailsService userDetailsService(PasswordEncoder encoder) {
        return new InMemoryUserDetailsManager(
                User.withUsername(username)
                        .password(encoder.encode(password))
                        .roles("USER")
                        .build());
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS));

        if (securityEnabled) {
            http
                    .authorizeHttpRequests(auth -> auth
                            .requestMatchers(
                                    "/actuator/health",
                                    "/v3/api-docs/**",
                                    "/swagger-ui/**",
                                    "/swagger-ui.html"
                            ).permitAll()
                            .anyRequest().authenticated())
                    .httpBasic(Customizer.withDefaults());
        } else {
            http.authorizeHttpRequests(auth -> auth.anyRequest().permitAll());
        }
        return http.build();
    }
}
