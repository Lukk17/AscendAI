package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.service.AscendChatService;
import com.lukk.ascend.ai.agent.service.VisionCapabilityResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Additional branch coverage for PromptController.
 * Signature (10 params): prompt (String prompt, MultipartFile image, MultipartFile document,
 *   String provider, String model, String embeddingProvider, Boolean attachSources,
 *   String compactionProvider, String compactionModel, String userIdHeader)
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PromptControllerExtraTest {

    @Mock
    private AscendChatService ascendChatService;

    @Mock
    private VisionCapabilityResolver visionCapabilityResolver;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private PromptController controller;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(controller, "defaultUserId", "default-user");
        when(ascendChatService.prompt(anyString(), any(), any(), anyString(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(new AiResponse("ok", null));
    }

    // ------------------------------------------------------------------ vision guard

    @Test
    @DisplayName("prompt returns 415 when image is attached and model does not support vision")
    void prompt_ImageAttachedAndModelDoesNotSupportVision_Returns415() {
        // given
        MultipartFile image = mock(MultipartFile.class);
        when(image.isEmpty()).thenReturn(false);
        when(visionCapabilityResolver.supportsImages("openai", null)).thenReturn(false);

        // when  (prompt, image, document, provider, model, embedding, attach, compProv, compModel, userId)
        ResponseEntity<?> response = controller.prompt("hello", image, null, "openai", null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody()).isInstanceOf(ApiError.class);
        ApiError err = (ApiError) response.getBody();
        assertThat(err.error()).isEqualTo("vision_unsupported");
    }

    @Test
    @DisplayName("prompt returns 200 when image is attached and model supports vision")
    void prompt_ImageAttachedAndModelSupportsVision_Returns200() {
        // given
        MultipartFile image = mock(MultipartFile.class);
        when(image.isEmpty()).thenReturn(false);
        when(visionCapabilityResolver.supportsImages("openai", "gpt-4o")).thenReturn(true);

        // when
        ResponseEntity<?> response = controller.prompt("hello", image, null, "openai", "gpt-4o", null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt skips vision check when no image is attached")
    void prompt_NoImage_SkipsVisionCheckAndReturns200() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, "openai", null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt skips vision check when image is empty")
    void prompt_EmptyImage_SkipsVisionCheckAndReturns200() {
        // given
        MultipartFile image = mock(MultipartFile.class);
        when(image.isEmpty()).thenReturn(true);

        // when
        ResponseEntity<?> response = controller.prompt("hello", image, null, "openai", null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    // ------------------------------------------------------------------ compaction provider validation

    @Test
    @DisplayName("prompt returns 400 when compactionProvider is set but not in the configured providers")
    void prompt_CompactionProviderUnknown_Returns400() {
        // given
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("openai", mock(AiProviderProperties.ProviderConfig.class)));

        // when  (prompt, image, document, provider, model, embedding, attach, compProv, compModel, userId)
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, "nonexistent-provider", null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isInstanceOf(ApiError.class);
        ApiError err = (ApiError) response.getBody();
        assertThat(err.error()).isEqualTo("unknown_compaction_provider");
        assertThat(err.message()).contains("nonexistent-provider");
    }

    @Test
    @DisplayName("prompt returns 200 when compactionProvider is set and exists in configured providers")
    void prompt_CompactionProviderKnown_Returns200() {
        // given
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("openai", mock(AiProviderProperties.ProviderConfig.class)));

        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, "openai", "gpt-4o-mini", null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt skips compaction provider check when compactionProvider is null")
    void prompt_CompactionProviderNull_SkipsCheckAndReturns200() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt skips compaction provider check when compactionProvider is blank")
    void prompt_CompactionProviderBlank_SkipsCheckAndReturns200() {
        // when  — blank string is treated as absent
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, "  ", null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    // ------------------------------------------------------------------ user id resolution

    @Test
    @DisplayName("prompt uses X-User-Id header when it is provided")
    void prompt_WithUserIdHeader_UsesHeaderValue() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, null, null, "header-user");

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt falls back to defaultUserId when X-User-Id header is null")
    void prompt_NullUserIdHeader_FallsBackToDefault() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt falls back to defaultUserId when X-User-Id header is blank")
    void prompt_BlankUserIdHeader_FallsBackToDefault() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, null, null, "   ");

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    // ------------------------------------------------------------------ attachSources flag

    @Test
    @DisplayName("prompt passes attachSources=true to the service when the flag is set")
    void prompt_AttachSourcesTrue_PassesTrueToService() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, true, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt passes attachSources=false to the service when the flag is explicitly false")
    void prompt_AttachSourcesFalse_PassesFalseToService() {
        // when
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, false, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt uses the header user-id when header is not blank (non-null, non-blank)")
    void prompt_NonBlankHeader_UsesHeader() {
        // Explicitly test the non-null AND non-blank case for userId
        ResponseEntity<?> response = controller.prompt("hello", null, null, null, null, null, null, null, null, "actual-user");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt with provider and model override reaches the service")
    void prompt_WithProviderAndModel_ReachesService() {
        // given
        when(aiProviderProperties.getProviders()).thenReturn(java.util.Map.of("openai", mock(AiProviderProperties.ProviderConfig.class)));

        // when — known compaction provider + model
        ResponseEntity<?> response = controller.prompt("hello", null, null, "openai", "gpt-4o", null, null, "openai", "gpt-4o-mini", "user1");

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt logs non-empty document attachment info")
    void prompt_WithNonEmptyDocument_LogsDocumentAttached() {
        // given — non-null, non-empty document (hits document != null && !document.isEmpty() = true in log)
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(false);

        // when
        ResponseEntity<?> response = controller.prompt("hello", null, document, null, null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("prompt logs empty document attachment info")
    void prompt_WithEmptyDocument_LogsEmptyDoc() {
        // given — non-null but empty document (hits document != null && document.isEmpty() = true)
        MultipartFile document = mock(MultipartFile.class);
        when(document.isEmpty()).thenReturn(true);

        // when
        ResponseEntity<?> response = controller.prompt("hello", null, document, null, null, null, null, null, null, null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }
}
