from pathlib import Path

import pytest

from src.config.config import (
    DEFAULT_QUALITY,
    LANGUAGE_MODEL_OVERRIDES,
    MAX_DETECTOR_DOWNSCALE_RATIO,
    MEASURED_WORST_PAGE_SECONDS,
    ModelPair,
    QualityProfile,
    Settings,
)
from tests.conftest import OFF_FAMILY_PAIR


class TestSettingsDefaults:
    def test_default_api_host(self):
        # Then
        assert Settings().API_HOST == "0.0.0.0"  # noqa: S104

    def test_default_api_port(self):
        # Then
        assert Settings().API_PORT == 7022

    def test_default_log_level(self):
        # Then
        assert Settings().LOG_LEVEL == "INFO"

    def test_default_language(self):
        # Then
        assert Settings().DEFAULT_LANGUAGE == "en"

    def test_default_max_file_size(self):
        # Then
        assert Settings().MAX_FILE_SIZE_MB == 50

    def test_default_engine_cache_max_size(self):
        # Then: counts cached engines, the pre-cached default pair plus one slot that
        # stays empty until a language is opted back in with a pair of its own
        assert Settings().ENGINE_CACHE_MAX_SIZE == 2

    def test_default_model_pair_is_the_small_member_of_the_current_family(self):
        # Then - explicit, because the library's own default for these languages is the
        # medium member (see ADR-007)
        assert Settings().OCR_TEXT_DETECTION_MODEL == "PP-OCRv6_small_det"
        assert Settings().OCR_TEXT_RECOGNITION_MODEL == "PP-OCRv6_small_rec"

    def test_no_language_carries_a_model_pair_of_its_own(self):
        # Then: ru and korean were the only two, and both are switched off until the
        # small detector is measured with their recognisers
        assert LANGUAGE_MODEL_OVERRIDES == {}

    def test_default_supported_languages_are_the_ones_the_default_pair_reads(self):
        # Then. "japan" is PaddleOCR's own code for Japanese, not the ISO "ja".
        assert Settings().SUPPORTED_LANGUAGES == ("en", "pl", "de", "fr", "es", "it", "pt", "nl", "ch", "japan")

    @pytest.mark.parametrize("language", ["ru", "korean"])
    def test_russian_and_korean_are_switched_off(self, language):
        # Then: their PP-OCRv5 server detector peaked above the container limit
        assert language not in Settings().SUPPORTED_LANGUAGES

    def test_default_mcp_file_uri_root_unset(self):
        # Then
        assert Settings().MCP_FILE_URI_ROOT is None

    def test_default_mcp_allowed_hosts_empty(self):
        # Then
        assert Settings().MCP_ALLOWED_HOSTS == ()

    def test_default_mcp_download_timeout(self):
        # Then
        assert pytest.approx(30.0) == Settings().MCP_DOWNLOAD_TIMEOUT_SECONDS


class TestSettingsEnvOverride:
    def test_override_api_port(self, monkeypatch):
        # Given
        monkeypatch.setenv("API_PORT", "9999")

        # Then
        assert Settings().API_PORT == 9999

    def test_override_default_language(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "pl")

        # Then
        assert Settings().DEFAULT_LANGUAGE == "pl"

    def test_override_max_file_size(self, monkeypatch):
        # Given
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")

        # Then
        assert Settings().MAX_FILE_SIZE_MB == 100

    def test_override_log_level(self, monkeypatch):
        # Given
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Then
        assert Settings().LOG_LEVEL == "DEBUG"

    def test_override_mcp_file_uri_root(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_FILE_URI_ROOT", "/var/lib/ascend-ocr/uploads")

        # Then
        assert Settings().MCP_FILE_URI_ROOT == "/var/lib/ascend-ocr/uploads"

    def test_override_mcp_allowed_hosts_csv(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "host.docker.internal,localhost,127.0.0.1")

        # Then
        assert Settings().MCP_ALLOWED_HOSTS == ("host.docker.internal", "localhost", "127.0.0.1")

    def test_override_mcp_allowed_hosts_csv_strips_whitespace(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "  host.docker.internal , localhost  , ,127.0.0.1 ")

        # Then. Empty entries dropped, whitespace stripped from each.
        assert Settings().MCP_ALLOWED_HOSTS == ("host.docker.internal", "localhost", "127.0.0.1")

    def test_override_supported_languages_csv(self, monkeypatch):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", "en,pl,fr")

        # Then
        assert Settings().SUPPORTED_LANGUAGES == ("en", "pl", "fr")

    def test_override_model_pair(self, monkeypatch):
        # Given - switching family member is two environment variables, no code change
        monkeypatch.setenv("OCR_TEXT_DETECTION_MODEL", "PP-OCRv6_medium_det")
        monkeypatch.setenv("OCR_TEXT_RECOGNITION_MODEL", "PP-OCRv6_medium_rec")

        # Then
        settings = Settings()
        assert settings.OCR_TEXT_DETECTION_MODEL == "PP-OCRv6_medium_det"
        assert settings.OCR_TEXT_RECOGNITION_MODEL == "PP-OCRv6_medium_rec"


class TestSettingsValidation:
    def test_invalid_log_level_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_invalid_language_pattern_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "../etc")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_model_name_with_path_traversal_rejected(self, monkeypatch):
        # Given - the model name reaches a library that resolves it against a cache directory
        monkeypatch.setenv("OCR_TEXT_DETECTION_MODEL", "../../etc/passwd")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_empty_model_name_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_TEXT_RECOGNITION_MODEL", "")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_six_letter_default_language_accepted(self, monkeypatch):
        # Given. "korean" is the longest PaddleOCR-native code, so the pattern still
        # admits it and a request in it reaches the unsupported-language refusal.
        monkeypatch.setenv("DEFAULT_LANGUAGE", "korean")

        # Then
        assert Settings().DEFAULT_LANGUAGE == "korean"

    def test_seven_letter_default_language_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "abcdefg")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_max_file_size_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_a_leftover_request_timeout_in_the_environment_is_ignored(self, monkeypatch):
        # Given - a deployment that has not yet dropped the deleted setting
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "300")

        # Then - extra="ignore", so it neither binds nor refuses to start
        settings = Settings()
        assert not hasattr(settings, "OCR_REQUEST_TIMEOUT")
        assert not hasattr(settings, "OCR_MAX_PAGES")


class TestNewLimitsSettingsDefaults:
    def test_default_worker_count(self):
        # Then
        assert Settings().OCR_WORKER_COUNT == 1

    def test_default_page_allowance_headroom_is_the_rule_the_allowance_was_derived_with(self):
        # Then
        assert pytest.approx(4.5) == Settings().OCR_PAGE_ALLOWANCE_HEADROOM

    def test_default_dispatch_margin(self):
        # Then
        assert pytest.approx(5.0) == Settings().OCR_DISPATCH_MARGIN_SECONDS

    def test_default_pool_rebuild_max_consecutive(self):
        # Then
        assert Settings().OCR_POOL_REBUILD_MAX_CONSECUTIVE == 3


class TestNewLimitsSettingsOverrides:
    def test_override_worker_count(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_WORKER_COUNT", "2")

        # Then
        assert Settings().OCR_WORKER_COUNT == 2

    def test_override_page_allowance_headroom(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "6")

        # Then
        assert pytest.approx(6.0) == Settings().OCR_PAGE_ALLOWANCE_HEADROOM

    def test_override_dispatch_margin(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "10")

        # Then
        assert pytest.approx(10.0) == Settings().OCR_DISPATCH_MARGIN_SECONDS

    def test_override_pool_rebuild_max_consecutive(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_POOL_REBUILD_MAX_CONSECUTIVE", "5")

        # Then
        assert Settings().OCR_POOL_REBUILD_MAX_CONSECUTIVE == 5


class TestNewLimitsSettingsValidation:
    def test_zero_worker_count_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_WORKER_COUNT", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_page_allowance_headroom_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_dispatch_margin_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_pool_rebuild_max_consecutive_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_POOL_REBUILD_MAX_CONSECUTIVE", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()


SMALL_PAIR = ModelPair("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
SERVER_PAIR = OFF_FAMILY_PAIR


@pytest.fixture
def default_family_only(monkeypatch):
    """A deployment whose every language reads with the default pair, so the worst engine is the small one."""
    monkeypatch.setenv("SUPPORTED_LANGUAGES", "en,pl")
    monkeypatch.setenv("DEFAULT_LANGUAGE", "en")


class TestPageAllowance:
    def test_the_measured_worst_pages_are_the_in_container_high_mode_runs(self):
        # Then: the small detector's worst is a dense Polish A4 prose page, the server
        # detector's a plain 4200 x 4200 page, both bounded to 1536, fastest of three runs
        assert dict(MEASURED_WORST_PAGE_SECONDS) == {"PP-OCRv6_small_det": 25.1, "PP-OCRv5_server_det": 96.0}

    @pytest.mark.parametrize(("pair", "expected"), [(SMALL_PAIR, 25.1 * 4.5), (SERVER_PAIR, 96.0 * 4.5)])
    def test_a_page_is_allowed_the_headroom_times_its_own_engines_worst_measured_page(self, pair, expected):
        # Then
        assert pytest.approx(expected) == Settings().page_allowance_seconds(pair)

    def test_the_shipped_page_allowance_is_112_95_seconds(self):
        # Then: 4.5 x 25.1 s
        assert pytest.approx(112.95) == Settings().page_allowance_seconds(SMALL_PAIR)

    def test_a_detector_nobody_measured_is_allowed_the_slowest_measured_page(self):
        # Then
        assert pytest.approx(96.0 * 4.5) == Settings().page_allowance_seconds(
            ModelPair("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
        )

    def test_the_allowance_follows_the_headroom(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")

        # Then
        assert pytest.approx(50.2) == Settings().page_allowance_seconds(SMALL_PAIR)

    def test_the_worst_allowance_is_the_small_engines_while_every_supported_language_reads_with_it(self):
        # Then
        assert pytest.approx(25.1 * 4.5) == Settings().OCR_WORST_PAGE_ALLOWANCE_SECONDS

    def test_the_worst_allowance_counts_only_engines_a_language_can_reach(self, default_family_only):
        # Then
        assert pytest.approx(25.1 * 4.5) == Settings().OCR_WORST_PAGE_ALLOWANCE_SECONDS

    def test_a_language_opted_back_in_on_a_slower_detector_raises_the_worst_allowance(
        self, monkeypatch, off_family_language
    ):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", f"en,pl,{off_family_language}")

        # Then
        assert pytest.approx(96.0 * 4.5) == Settings().OCR_WORST_PAGE_ALLOWANCE_SECONDS

    def test_the_default_language_is_reachable_even_when_the_list_is_empty(self, monkeypatch, off_family_language):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", "")
        monkeypatch.setenv("DEFAULT_LANGUAGE", off_family_language)

        # Then
        assert pytest.approx(96.0 * 4.5) == Settings().OCR_WORST_PAGE_ALLOWANCE_SECONDS

    def test_a_language_resolves_to_its_override_or_the_configured_pair(self, off_family_language):
        # Then
        loaded = Settings()
        assert loaded.model_pair(off_family_language) == SERVER_PAIR
        assert loaded.model_pair("pl") == SMALL_PAIR

    def test_the_shipped_languages_reach_only_the_small_pair(self):
        # Then: no supported language loads the PP-OCRv5 server detector, so the image
        # preloads nothing else
        assert Settings().reachable_model_pairs() == frozenset({SMALL_PAIR})

    def test_every_engine_a_supported_language_can_load_is_reachable_once(self, monkeypatch, off_family_language):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", f"en,pl,{off_family_language}")

        # Then
        assert Settings().reachable_model_pairs() == frozenset({SMALL_PAIR, SERVER_PAIR})

    def test_the_default_languages_engine_is_reachable_even_when_the_list_is_empty(
        self, monkeypatch, off_family_language
    ):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", "")
        monkeypatch.setenv("DEFAULT_LANGUAGE", off_family_language)

        # Then
        assert Settings().reachable_model_pairs() == frozenset({SERVER_PAIR})

    def test_the_allowance_is_not_settable_from_the_environment(self, monkeypatch):
        # Given: the removed single allowance, left behind in an environment
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "45")

        # Then
        loaded = Settings()
        assert not hasattr(loaded, "OCR_PAGE_TIMEOUT_SECONDS")
        assert pytest.approx(25.1 * 4.5) == loaded.page_allowance_seconds(SMALL_PAIR)


class TestDerivedProperties:
    def test_reclamation_grace_is_the_engines_own_allowance_plus_the_margin(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "5")

        # Then
        loaded = Settings()
        assert pytest.approx(50.2 + 5.0) == loaded.reclamation_grace_seconds(SMALL_PAIR)
        assert pytest.approx(192.0 + 5.0) == loaded.reclamation_grace_seconds(SERVER_PAIR)

    def test_reclamation_grace_follows_the_margin(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "10")

        # Then
        assert pytest.approx(60.2) == Settings().reclamation_grace_seconds(SMALL_PAIR)


class TestJobSettings:
    def test_defaults(self):
        # Then - the values design.md's number table derives
        settings = Settings()
        assert settings.OCR_JOB_MAX_PAGES == 100
        assert pytest.approx(3600.0) == settings.OCR_JOB_RETENTION_SECONDS
        assert settings.OCR_JOB_MAX_RETAINED == 1000
        assert settings.OCR_JOB_QUEUE_MAX_PAGES == 200
        assert settings.OCR_JOB_QUEUE_MAX_DOCUMENTS == 8
        assert "ascend-ocr-jobs" in settings.OCR_JOBS_DIR

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [
            ("OCR_JOB_MAX_PAGES", "40", 40),
            ("OCR_JOB_RETENTION_SECONDS", "900", 900.0),
            ("OCR_JOB_MAX_RETAINED", "50", 50),
            ("OCR_JOB_QUEUE_MAX_PAGES", "400", 400),
            ("OCR_JOB_QUEUE_MAX_DOCUMENTS", "4", 4),
        ],
    )
    def test_each_setting_can_be_overridden(self, monkeypatch, name, value, expected):
        # Given
        monkeypatch.setenv(name, value)

        # Then
        assert getattr(Settings(), name) == expected

    def test_the_jobs_directory_can_be_overridden(self, monkeypatch, tmp_path):
        # Given
        monkeypatch.setenv("OCR_JOBS_DIR", str(tmp_path))

        # Then
        assert str(tmp_path) == Settings().OCR_JOBS_DIR

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("OCR_JOB_MAX_PAGES", "0"),
            ("OCR_JOB_RETENTION_SECONDS", "0"),
            ("OCR_JOB_MAX_RETAINED", "0"),
            ("OCR_JOB_QUEUE_MAX_PAGES", "0"),
            ("OCR_JOB_QUEUE_MAX_DOCUMENTS", "0"),
        ],
    )
    def test_each_setting_rejects_a_value_out_of_range(self, monkeypatch, name, value):
        # Given
        monkeypatch.setenv(name, value)

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_a_queue_that_could_not_hold_one_maximal_document_is_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")
        monkeypatch.setenv("OCR_JOB_QUEUE_MAX_PAGES", "99")

        # Then - the message names both settings, because either one could be the fix
        with pytest.raises(ValueError, match=r"OCR_JOB_QUEUE_MAX_PAGES.*OCR_JOB_MAX_PAGES"):
            Settings()

    def test_a_queue_bound_equal_to_the_page_ceiling_is_accepted(self, monkeypatch):
        # Given - exactly one maximal document may wait
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")
        monkeypatch.setenv("OCR_JOB_QUEUE_MAX_PAGES", "100")

        # Then
        assert Settings().OCR_JOB_QUEUE_MAX_PAGES == 100


class TestResultStoreSettings:
    def test_defaults(self):
        # Then
        settings = Settings()
        assert settings.OCR_RESULT_S3_ENDPOINT == "http://localhost:9070"
        assert settings.OCR_RESULT_S3_BUCKET == "ocr-results"
        assert settings.OCR_RESULT_S3_ACCESS_KEY == ""
        assert settings.OCR_RESULT_S3_SECRET_KEY == ""

    def test_the_public_endpoint_follows_the_endpoint_when_it_is_not_set(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_RESULT_S3_ENDPOINT", "http://host.docker.internal:9070")

        # Then
        settings = Settings()
        assert settings.OCR_RESULT_S3_PUBLIC_ENDPOINT == "http://host.docker.internal:9070"

    def test_the_public_endpoint_does_not_follow_the_endpoint_when_it_is_set(self, monkeypatch):
        # Given - the address this service reaches is not the one a caller reaches
        monkeypatch.setenv("OCR_RESULT_S3_ENDPOINT", "http://host.docker.internal:9070")
        monkeypatch.setenv("OCR_RESULT_S3_PUBLIC_ENDPOINT", "http://localhost:9070")

        # Then
        assert Settings().OCR_RESULT_S3_PUBLIC_ENDPOINT == "http://localhost:9070"

    def test_the_credentials_can_be_set(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_RESULT_S3_ACCESS_KEY", "admin")
        monkeypatch.setenv("OCR_RESULT_S3_SECRET_KEY", "password")

        # Then
        settings = Settings()
        assert settings.OCR_RESULT_S3_ACCESS_KEY == "admin"
        assert settings.OCR_RESULT_S3_SECRET_KEY == "password"

    @pytest.mark.parametrize("endpoint", ["localhost:9070", "ftp://store/", "/not-a-url", "http://a b"])
    def test_an_endpoint_that_is_not_an_absolute_http_url_is_rejected(self, monkeypatch, endpoint):
        # Given
        monkeypatch.setenv("OCR_RESULT_S3_ENDPOINT", endpoint)

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_a_public_endpoint_that_is_not_an_absolute_http_url_is_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_RESULT_S3_PUBLIC_ENDPOINT", "not-a-url")

        # Then
        with pytest.raises(ValueError):
            Settings()

    @pytest.mark.parametrize("bucket", ["Ocr-Results", "ab", "results_bucket", "-results", "x" * 64])
    def test_a_name_no_object_store_would_accept_is_rejected(self, monkeypatch, bucket):
        # Given
        monkeypatch.setenv("OCR_RESULT_S3_BUCKET", bucket)

        # Then
        with pytest.raises(ValueError):
            Settings()


class TestJobDerivedProperties:
    def test_the_reading_ceiling_is_the_page_ceiling_times_the_worst_allowance(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")

        # Then: a hundred pages on the small detector at 4.5 x 25.1 s
        assert pytest.approx(11_295.0) == Settings().OCR_JOB_READING_CEILING_SECONDS

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [("OCR_JOB_MAX_PAGES", "50", 50 * 50.2), ("OCR_PAGE_ALLOWANCE_HEADROOM", "3", 100 * 75.3)],
    )
    def test_the_reading_ceiling_follows_every_one_of_its_inputs(
        self, monkeypatch, default_family_only, name, value, expected
    ):
        # Given
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")
        monkeypatch.setenv(name, value)

        # Then
        assert pytest.approx(expected) == Settings().OCR_JOB_READING_CEILING_SECONDS

    def test_the_reading_ceiling_is_not_settable_from_the_environment(self, monkeypatch, default_family_only):
        # Given
        monkeypatch.setenv("OCR_JOB_READING_CEILING_SECONDS", "999")
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "10")
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")

        # Then: an unknown variable is ignored, so it stays derived
        assert pytest.approx(502.0) == Settings().OCR_JOB_READING_CEILING_SECONDS

    def test_the_maximum_lifetime_is_the_whole_queue_plus_one_maximal_document(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_JOB_QUEUE_MAX_PAGES", "200")
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")

        # Then: every page of it on the slowest engine a language can reach, 300 x 112.95 s
        assert pytest.approx(33_885.0) == Settings().OCR_JOB_MAX_LIFETIME_SECONDS

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [
            ("OCR_JOB_QUEUE_MAX_PAGES", "300", 400 * 50.2),
            ("OCR_JOB_MAX_PAGES", "50", 250 * 50.2),
            ("OCR_PAGE_ALLOWANCE_HEADROOM", "3", 300 * 75.3),
        ],
    )
    def test_the_maximum_lifetime_follows_every_one_of_its_inputs(
        self, monkeypatch, default_family_only, name, value, expected
    ):
        # Given
        monkeypatch.setenv("OCR_JOB_QUEUE_MAX_PAGES", "200")
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")
        monkeypatch.setenv(name, value)

        # Then
        assert pytest.approx(expected) == Settings().OCR_JOB_MAX_LIFETIME_SECONDS

    def test_the_maximum_lifetime_is_not_settable_from_the_environment(self, monkeypatch, default_family_only):
        # Given
        monkeypatch.setenv("OCR_JOB_MAX_LIFETIME_SECONDS", "1")
        monkeypatch.setenv("OCR_JOB_QUEUE_MAX_PAGES", "200")
        monkeypatch.setenv("OCR_JOB_MAX_PAGES", "100")
        monkeypatch.setenv("OCR_PAGE_ALLOWANCE_HEADROOM", "2")

        # Then: an unknown variable is ignored, so it stays derived
        assert pytest.approx(300 * 50.2) == Settings().OCR_JOB_MAX_LIFETIME_SECONDS


class TestDeletedSettingsHaveNoConsumers:
    def test_no_module_reads_the_deleted_request_timeout_or_derived_page_limit(self):
        # Given - both were deleted with this change, and a consumer left behind would
        # raise AttributeError only on the path that happens to reach it
        source_root = Path(__file__).resolve().parents[2] / "src"

        # When
        offenders = [
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*.py")
            if "OCR_REQUEST_TIMEOUT" in path.read_text(encoding="utf-8")
            or "OCR_MAX_PAGES" in path.read_text(encoding="utf-8")
        ]

        # Then
        assert offenders == []


DELETED_PAGE_SETTINGS = [
    "OCR_MAX_INFERENCE_PIXELS",
    "OCR_DETECTOR_MAX_SIDE",
    "OCR_SCRATCH_DIR",
    "OCR_PAGE_TIMEOUT_SECONDS",
    "OCR_RECLAMATION_GRACE_SECONDS",
]


class TestDeletedPageSettingsHaveNoConsumers:
    @pytest.mark.parametrize("name", DELETED_PAGE_SETTINGS)
    def test_no_module_reads_a_setting_this_change_replaced(self, name):
        # Given: a consumer left behind would raise AttributeError only on the path
        # that happens to reach it
        source_root = Path(__file__).resolve().parents[2] / "src"

        # When
        offenders = [
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*.py")
            if f"settings.{name}" in path.read_text(encoding="utf-8")
        ]

        # Then
        assert offenders == []

    @pytest.mark.parametrize("name", DELETED_PAGE_SETTINGS)
    def test_a_leftover_value_in_the_environment_is_ignored(self, monkeypatch, name):
        # Given
        monkeypatch.setenv(name, "1")

        # When
        loaded = Settings()

        # Then
        assert not hasattr(loaded, name)


class TestQualityProfile:
    def test_the_render_scale_is_the_resolution_over_the_points_per_inch_of_a_pdf(self):
        # Then
        assert pytest.approx(300 / 72) == QualityProfile(render_dpi=300, detector_max_side=1536).render_scale

    def test_the_largest_supported_long_side_is_us_legal_at_the_resolution(self):
        # Then: 14 inches, the longest standard page the service targets
        assert QualityProfile(render_dpi=300, detector_max_side=1536).max_long_side_pixels == 4200
        assert QualityProfile(render_dpi=150, detector_max_side=1024).max_long_side_pixels == 2100

    def test_the_largest_inference_is_a_square_at_the_largest_long_side(self):
        # Then
        assert QualityProfile(render_dpi=150, detector_max_side=1024).max_inference_pixels == 2100 * 2100

    def test_a_pair_at_the_measured_ratio_ceiling_is_accepted(self):
        # Given: 14 in x 72 dpi is 1008 px, and 1008 / 3.3 is 305.45
        profile = QualityProfile(render_dpi=72, detector_max_side=306)

        # Then
        assert profile.worst_downscale_ratio <= MAX_DETECTOR_DOWNSCALE_RATIO

    def test_a_pair_beyond_the_measured_ratio_ceiling_is_refused(self):
        # When / Then: 4200 / 1024 is 4.1x, between the clean 3.3x and the garbage 6.85x
        with pytest.raises(ValueError, match=r"300:1024 .*4\.10x"):
            QualityProfile(render_dpi=300, detector_max_side=1024)

    @pytest.mark.parametrize(("dpi", "side"), [(0, 1536), (300, 0), (-1, 1536)])
    def test_a_pair_with_a_non_positive_number_is_refused(self, dpi, side):
        # When / Then
        with pytest.raises(ValueError, match="positive"):
            QualityProfile(render_dpi=dpi, detector_max_side=side)

    def test_the_pair_is_written_the_way_the_setting_reads_it(self):
        # Then
        assert str(QualityProfile(render_dpi=150, detector_max_side=1024)) == "150:1024"


class TestQualitySettings:
    def test_the_default_mode_is_high(self):
        # Then
        assert DEFAULT_QUALITY == "high"

    def test_the_shipped_pairs(self):
        # When
        loaded = Settings()

        # Then
        assert QualityProfile(render_dpi=150, detector_max_side=1024) == loaded.OCR_QUALITY_NORMAL
        assert QualityProfile(render_dpi=300, detector_max_side=1536) == loaded.OCR_QUALITY_HIGH

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("normal", QualityProfile(render_dpi=150, detector_max_side=1024)),
            ("high", QualityProfile(render_dpi=300, detector_max_side=1536)),
        ],
    )
    def test_each_mode_resolves_to_its_own_pair(self, mode, expected):
        # Then
        assert Settings().quality_profile(mode) == expected

    def test_a_pair_is_read_from_the_environment_as_one_value(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_QUALITY_HIGH", " 200 : 1280 ")

        # Then
        assert Settings().quality_profile("high") == QualityProfile(render_dpi=200, detector_max_side=1280)

    @pytest.mark.parametrize("value", ["300", "300:", ":1536", "300:1536:1", "300dpi:1536", "high", ""])
    def test_a_malformed_pair_stops_the_service_from_starting(self, monkeypatch, value):
        # Given
        monkeypatch.setenv("OCR_QUALITY_NORMAL", value)

        # When / Then
        with pytest.raises(ValueError, match="OCR_QUALITY_NORMAL"):
            Settings()

    def test_a_pair_beyond_the_ratio_ceiling_stops_the_service_from_starting(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_QUALITY_HIGH", "300:1024")

        # When / Then
        with pytest.raises(ValueError, match=r"3\.3x"):
            Settings()


class TestSourcePixelCeiling:
    def test_the_default_is_pillows_own_decompression_bomb_threshold(self):
        # Then
        assert Settings().OCR_MAX_SOURCE_PIXELS == 89_478_485

    def test_it_can_be_overridden(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_MAX_SOURCE_PIXELS", "100000000")

        # Then
        assert Settings().OCR_MAX_SOURCE_PIXELS == 100_000_000

    def test_zero_is_refused(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_MAX_SOURCE_PIXELS", "0")

        # When / Then
        with pytest.raises(ValueError):
            Settings()
