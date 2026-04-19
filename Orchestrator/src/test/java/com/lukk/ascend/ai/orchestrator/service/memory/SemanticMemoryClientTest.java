package com.lukk.ascend.ai.orchestrator.service.memory;

import com.lukk.ascend.ai.orchestrator.config.properties.SemanticMemoryProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Answers;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SemanticMemoryClientTest {

    private static final String DEFAULT_USER_ID = "user1";
    private static final String QUERY = "Find memory";
    private static final int LIMIT = 5;
    private static final String FACT = "User uses Python";
    private static final String EMBEDDING_PROVIDER = "lmstudio";

    @Mock(answer = Answers.RETURNS_DEEP_STUBS)
    private RestClient.Builder restClientBuilder;

    @Mock
    private SemanticMemoryProperties properties;

    @InjectMocks
    private SemanticMemoryClient semanticMemoryClient;

    @Test
    void search_WhenDisabled_ThenReturnsEmptyList() {
        // given
        when(properties.isEnabled()).thenReturn(false);

        // when
        List<SemanticMemoryItem> result = semanticMemoryClient.search(DEFAULT_USER_ID, QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEmpty();
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    @SuppressWarnings("unchecked")
    void search_WhenEnabledAndSuccessful_ThenReturnsItems() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        List<SemanticMemoryItem> expectedItems = List.of(new SemanticMemoryItem("1", "user1", "Memory", 0.9d, Instant.now(), Map.of()));

        when(restClientBuilder.build().get()
                .uri(anyString(), eq(DEFAULT_USER_ID), eq(QUERY), eq(LIMIT), eq(EMBEDDING_PROVIDER))
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenReturn(expectedItems);

        // when
        List<SemanticMemoryItem> result = semanticMemoryClient.search(DEFAULT_USER_ID, QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEqualTo(expectedItems);
    }

    @Test
    @SuppressWarnings("unchecked")
    void search_WhenApiResponseIs404_ThenGracefullyReturnsEmptyList() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        RestClientResponseException exception = new HttpClientErrorException(HttpStatus.NOT_FOUND);

        when(restClientBuilder.build().get()
                .uri(anyString(), anyString(), anyString(), any(Integer.class), anyString())
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenThrow(exception);

        // when
        List<SemanticMemoryItem> result = semanticMemoryClient.search(DEFAULT_USER_ID, QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    void search_WhenGeneralException_ThenGracefullyReturnsEmptyList() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        when(restClientBuilder.build().get()
                .uri(anyString(), anyString(), anyString(), any(Integer.class), anyString())
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenThrow(new RuntimeException("Connection Refused"));

        // when
        List<SemanticMemoryItem> result = semanticMemoryClient.search(DEFAULT_USER_ID, QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void insertMemory_WhenDisabled_ThenDoesNothing() {
        // given
        when(properties.isEnabled()).thenReturn(false);

        // when
        semanticMemoryClient.insertMemory(DEFAULT_USER_ID, FACT, EMBEDDING_PROVIDER);

        // then
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    void insertMemory_WhenEnabled_ThenPostsSuccessfully() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        RestClient restClient = mock(RestClient.class);
        when(restClientBuilder.build()).thenReturn(restClient);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.body(anyMap())).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenReturn(responseSpecMock);
        when(responseSpecMock.onStatus(any(), any())).thenReturn(responseSpecMock);

        // when / then — no exception
        semanticMemoryClient.insertMemory(DEFAULT_USER_ID, FACT, EMBEDDING_PROVIDER);
    }
}