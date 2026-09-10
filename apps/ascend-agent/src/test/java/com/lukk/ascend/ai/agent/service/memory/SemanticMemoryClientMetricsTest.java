package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Answers;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SemanticMemoryClientMetricsTest {

    private static final String EMB_PROVIDER = "openai";

    @Mock(answer = Answers.RETURNS_DEEP_STUBS)
    private RestClient.Builder restClientBuilder;

    private MeterRegistry registry;
    private SemanticMemoryProperties properties;
    private SemanticMemoryClient client;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        properties = new SemanticMemoryProperties();
        properties.setEnabled(true);
        properties.setBaseUrl("http://memory");
        client = new SemanticMemoryClient(restClientBuilder, properties, registry);
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("search registers memory.search.duration timer with embedding_provider and outcome=ok tags")
    void search_Success_RegistersSearchDurationTimerWithOkOutcome() {
        // given
        when(restClientBuilder.build().get()
                .uri(anyString(), anyString(), anyString(), any(Integer.class), anyString())
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenReturn(List.of());

        // when
        client.search("user1", "query", 5, EMB_PROVIDER);

        // then
        Timer timer = registry.find("memory.search.duration")
                .tag("embedding_provider", EMB_PROVIDER)
                .tag("outcome", "ok")
                .timer();
        assertThat(timer).isNotNull();
        assertThat(timer.count()).isEqualTo(1);
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("search registers memory.search.duration timer with outcome=error when search fails")
    void search_Failure_RegistersSearchDurationTimerWithErrorOutcome() {
        // given
        when(restClientBuilder.build().get()
                .uri(anyString(), anyString(), anyString(), any(Integer.class), anyString())
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenThrow(new RuntimeException("connection refused"));

        // when
        client.search("user1", "query", 5, EMB_PROVIDER);

        // then
        Timer timer = registry.find("memory.search.duration")
                .tag("embedding_provider", EMB_PROVIDER)
                .tag("outcome", "error")
                .timer();
        assertThat(timer).isNotNull();
        assertThat(timer.count()).isEqualTo(1);
    }

    @Test
    @DisplayName("insertMemory registers memory.insert.failed counter with reason=4xx tag on 4xx error")
    void insertMemory_4xxError_RegistersInsertFailedCounterWith4xxReason() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpec = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpec = mock(RestClient.ResponseSpec.class);
        RestClient restClient = mock(RestClient.class);
        when(restClientBuilder.build()).thenReturn(restClient);
        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpec);
        when(bodySpec.body(anyMap())).thenReturn(bodySpec);
        when(bodySpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.toBodilessEntity()).thenThrow(new HttpClientErrorException(HttpStatus.BAD_REQUEST));

        // when
        assertThatThrownBy(() -> client.insertMemory("user1", "fact", EMB_PROVIDER))
                .isInstanceOf(HttpClientErrorException.class);

        // then
        Counter counter = registry.find("memory.insert.failed")
                .tag("embedding_provider", EMB_PROVIDER)
                .tag("reason", "4xx")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(1.0);
    }
}
