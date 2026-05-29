package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Answers;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Targets the gaps left in {@link SemanticMemoryClient} JaCoCo report:
 * non-404 RestClientResponseException branch on search; wipe disabled / wipe error;
 * delete disabled / delete error; insert disabled with non-blank user.
 */
@ExtendWith(MockitoExtension.class)
class SemanticMemoryClientExtraTest {

    private static final String USER = "u1";
    private static final String EMB = "lmstudio";

    @Mock(answer = Answers.RETURNS_DEEP_STUBS)
    private RestClient.Builder restClientBuilder;

    @Mock
    private SemanticMemoryProperties properties;

    @InjectMocks
    private SemanticMemoryClient client;

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("search returns empty list and logs warning when a non-404 HTTP error occurs")
    void search_LogsWarn_WhenNon404HttpError() {
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");
        RestClientResponseException err = new HttpServerErrorException(HttpStatus.SERVICE_UNAVAILABLE);

        when(restClientBuilder.build().get()
                .uri(anyString(), anyString(), anyString(), any(Integer.class), anyString())
                .retrieve()
                .body(any(ParameterizedTypeReference.class)))
                .thenThrow(err);

        List<SemanticMemoryItem> result = client.search(USER, "q", 5, EMB);

        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("wipeUserMemory skips the HTTP call when semantic memory is disabled")
    void wipeUserMemory_WhenDisabled_ThenSkipsHttpCall() {
        when(properties.isEnabled()).thenReturn(false);

        client.wipeUserMemory(USER, EMB);

        verifyNoInteractions(restClientBuilder);
    }

    @Test
    @DisplayName("wipeUserMemory swallows RestClientResponseException and does not throw")
    void wipeUserMemory_SwallowsRestClientResponseException() {
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpec = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec respSpec = mock(RestClient.ResponseSpec.class);

        RestClient rest = mock(RestClient.class);
        when(restClientBuilder.build()).thenReturn(rest);
        when(rest.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpec);
        when(bodySpec.body(anyMap())).thenReturn(bodySpec);
        when(bodySpec.retrieve()).thenReturn(respSpec);
        when(respSpec.toBodilessEntity()).thenThrow(new HttpClientErrorException(HttpStatus.NOT_FOUND));

        // Should NOT throw — error is logged at warn and swallowed.
        assertThatCode(() -> client.wipeUserMemory(USER, EMB)).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("deleteMemory skips the HTTP call when semantic memory is disabled")
    void deleteMemory_WhenDisabled_ThenSkipsHttpCall() {
        when(properties.isEnabled()).thenReturn(false);

        client.deleteMemory(USER, "mem-1", EMB);

        verifyNoInteractions(restClientBuilder);
    }

    @Test
    @SuppressWarnings({"unchecked", "rawtypes"})
    @DisplayName("deleteMemory swallows RestClientResponseException and does not throw")
    void deleteMemory_SwallowsRestClientResponseException() {
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getBaseUrl()).thenReturn("http://memory");

        RestClient.RequestHeadersUriSpec deleteMock = mock(RestClient.RequestHeadersUriSpec.class);
        RestClient.RequestHeadersSpec<?> headersSpec = mock(RestClient.RequestHeadersSpec.class);
        RestClient.ResponseSpec respSpec = mock(RestClient.ResponseSpec.class);

        RestClient rest = mock(RestClient.class);
        when(restClientBuilder.build()).thenReturn(rest);
        when(rest.delete()).thenReturn(deleteMock);
        when(deleteMock.uri(anyString(), eq("mem-1"), eq(EMB))).thenAnswer(inv -> headersSpec);
        when(headersSpec.retrieve()).thenReturn(respSpec);
        when(respSpec.toBodilessEntity()).thenThrow(new HttpClientErrorException(HttpStatus.INTERNAL_SERVER_ERROR));

        assertThatCode(() -> client.deleteMemory(USER, "mem-1", EMB)).doesNotThrowAnyException();
    }
}
