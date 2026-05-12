package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
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
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import org.mockito.ArgumentCaptor;

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
    @SuppressWarnings("unchecked")
    void search_WhenEnabled_ThenSendsSnakeCaseUserIdQueryParam() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        when(restClientBuilder.build().get()
                .uri(anyString(), eq(DEFAULT_USER_ID), eq(QUERY), eq(LIMIT), eq(EMBEDDING_PROVIDER))
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenReturn(List.of());

        // when
        semanticMemoryClient.search(DEFAULT_USER_ID, QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        ArgumentCaptor<String> uriCaptor = ArgumentCaptor.forClass(String.class);
        verify(restClientBuilder.build().get()).uri(uriCaptor.capture(), eq(DEFAULT_USER_ID), eq(QUERY), eq(LIMIT), eq(EMBEDDING_PROVIDER));
        assertThat(uriCaptor.getValue()).contains("user_id={userId}");
        assertThat(uriCaptor.getValue()).doesNotContain("userId={userId}&");
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

        // when / then — no exception
        semanticMemoryClient.insertMemory(DEFAULT_USER_ID, FACT, EMBEDDING_PROVIDER);
    }

    @Test
    void wipeUserMemory_WhenEnabled_ThenPostsToWipeEndpoint() {
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

        // when
        semanticMemoryClient.wipeUserMemory(DEFAULT_USER_ID, EMBEDDING_PROVIDER);

        // then
        ArgumentCaptor<String> uriCaptor = ArgumentCaptor.forClass(String.class);
        verify(postMock).uri(uriCaptor.capture());
        assertThat(uriCaptor.getValue()).endsWith("/api/v1/memory/wipe");

        ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
        verify(bodySpecMock).body(bodyCaptor.capture());
        Map<String, Object> body = bodyCaptor.getValue();
        assertThat(body).containsEntry("user_id", DEFAULT_USER_ID);
        assertThat(body).containsEntry("provider", EMBEDDING_PROVIDER);
    }

    @Test
    void deleteMemory_WhenEnabled_ThenIssuesDeleteWithQueryParams() {
        // given
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        RestClient.RequestHeadersUriSpec deleteMock = mock(RestClient.RequestHeadersUriSpec.class);
        RestClient.RequestHeadersSpec<?> headersSpecMock = mock(RestClient.RequestHeadersSpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        RestClient restClient = mock(RestClient.class);
        when(restClientBuilder.build()).thenReturn(restClient);
        when(restClient.delete()).thenReturn(deleteMock);
        when(deleteMock.uri(anyString(), eq("mem-123"), eq(EMBEDDING_PROVIDER)))
                .thenAnswer(inv -> headersSpecMock);
        when(headersSpecMock.retrieve()).thenReturn(responseSpecMock);

        // when
        semanticMemoryClient.deleteMemory(DEFAULT_USER_ID, "mem-123", EMBEDDING_PROVIDER);

        // then
        ArgumentCaptor<String> uriCaptor = ArgumentCaptor.forClass(String.class);
        verify(deleteMock).uri(uriCaptor.capture(), eq("mem-123"), eq(EMBEDDING_PROVIDER));
        assertThat(uriCaptor.getValue()).contains("/api/v1/memory?memory_id={memoryId}&provider={provider}");
    }

    @Test
    void search_WhenUserIdIsBlank_ThenReturnsEmptyListWithoutHttpCall() {
        // when
        List<SemanticMemoryItem> result = semanticMemoryClient.search(" ", QUERY, LIMIT, EMBEDDING_PROVIDER);

        // then
        assertThat(result).isEmpty();
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    void insertMemory_WhenUserIdIsBlank_ThenNoOpWithoutHttpCall() {
        // when
        semanticMemoryClient.insertMemory("", FACT, EMBEDDING_PROVIDER);

        // then
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    void wipeUserMemory_WhenUserIdIsBlank_ThenNoOpWithoutHttpCall() {
        // when
        semanticMemoryClient.wipeUserMemory(null, EMBEDDING_PROVIDER);

        // then
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    void deleteMemory_WhenMemoryIdIsBlank_ThenNoOpWithoutHttpCall() {
        // when
        semanticMemoryClient.deleteMemory(DEFAULT_USER_ID, "", EMBEDDING_PROVIDER);

        // then
        verifyNoInteractions(restClientBuilder);
    }

    @Test
    @SuppressWarnings("unchecked")
    void insertMemory_WhenEnabled_ThenPostsSnakeCaseBody() {
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

        // when
        semanticMemoryClient.insertMemory(DEFAULT_USER_ID, FACT, EMBEDDING_PROVIDER);

        // then
        ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
        verify(bodySpecMock).body(bodyCaptor.capture());
        Map<String, Object> body = bodyCaptor.getValue();
        assertThat(body).containsEntry("user_id", DEFAULT_USER_ID);
        assertThat(body).containsEntry("text", FACT);
        assertThat(body).containsEntry("provider", EMBEDDING_PROVIDER);
        assertThat(body).doesNotContainKey("userId");
    }
}