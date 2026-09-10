from unittest.mock import patch

from src.config import cpu_limits
from src.config.cpu_limits import apply_cpu_thread_limit, detect_cpu_limit


class TestDetectCpuLimitCgroupV2:
    def test_reads_quota_and_period(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("400000 100000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", cgroup_file)

        # When / Then
        assert detect_cpu_limit() == 4

    def test_rounds_down_partial_cpu(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("250000 100000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", cgroup_file)

        # When / Then
        assert detect_cpu_limit() == 2

    def test_never_returns_zero_for_sub_one_cpu_quota(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("50000 100000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", cgroup_file)

        # When / Then
        assert detect_cpu_limit() == 1

    def test_unlimited_quota_falls_through(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("max 100000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", cgroup_file)
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", tmp_path / "missing-v1-quota")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "missing-v1-period")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=8):
            assert detect_cpu_limit() == 8

    def test_missing_file_falls_through(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "does-not-exist")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", tmp_path / "missing-v1-quota")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "missing-v1-period")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=6):
            assert detect_cpu_limit() == 6

    def test_malformed_content_falls_through(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "cpu.max"
        cgroup_file.write_text("not-a-number")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", cgroup_file)
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", tmp_path / "missing-v1-quota")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "missing-v1-period")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=6):
            assert detect_cpu_limit() == 6


class TestDetectCpuLimitCgroupV1:
    def test_reads_quota_and_period(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "no-v2-file")
        quota_file = tmp_path / "cpu.cfs_quota_us"
        period_file = tmp_path / "cpu.cfs_period_us"
        quota_file.write_text("200000\n")
        period_file.write_text("100000\n")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", quota_file)
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", period_file)

        # When / Then
        assert detect_cpu_limit() == 2

    def test_unlimited_quota_falls_back_to_cpu_count(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "no-v2-file")
        quota_file = tmp_path / "cpu.cfs_quota_us"
        period_file = tmp_path / "cpu.cfs_period_us"
        quota_file.write_text("-1")
        period_file.write_text("100000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", quota_file)
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", period_file)

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=12):
            assert detect_cpu_limit() == 12

    def test_missing_period_file_falls_back(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "no-v2-file")
        quota_file = tmp_path / "cpu.cfs_quota_us"
        quota_file.write_text("200000")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", quota_file)
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "does-not-exist")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=3):
            assert detect_cpu_limit() == 3


class TestDetectCpuLimitNoCgroup:
    def test_falls_back_to_cpu_count(self, tmp_path, monkeypatch):
        # Given no cgroup files at all
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "no-v2-file")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", tmp_path / "no-v1-quota")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "no-v1-period")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=16):
            assert detect_cpu_limit() == 16

    def test_falls_back_to_one_when_cpu_count_unknown(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(cpu_limits, "_CGROUP_V2_MAX_PATH", tmp_path / "no-v2-file")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_QUOTA_PATH", tmp_path / "no-v1-quota")
        monkeypatch.setattr(cpu_limits, "_CGROUP_V1_PERIOD_PATH", tmp_path / "no-v1-period")

        # When / Then
        with patch("src.config.cpu_limits.os.cpu_count", return_value=None):
            assert detect_cpu_limit() == 1


class TestApplyCpuThreadLimit:
    def test_sets_paddle_env_var_and_caps_opencv(self, monkeypatch):
        # Given
        monkeypatch.delenv("PADDLE_PDX_CPU_NUM_THREADS", raising=False)

        # When
        with (
            patch("src.config.cpu_limits.detect_cpu_limit", return_value=4),
            patch("src.config.cpu_limits.cv2") as mock_cv2,
        ):
            result = apply_cpu_thread_limit()

        # Then
        assert result == 4
        assert cpu_limits.os.environ["PADDLE_PDX_CPU_NUM_THREADS"] == "4"
        mock_cv2.setNumThreads.assert_called_once_with(4)

    def test_does_not_override_operator_supplied_env_var(self, monkeypatch):
        # Given
        monkeypatch.setenv("PADDLE_PDX_CPU_NUM_THREADS", "99")

        # When
        with (
            patch("src.config.cpu_limits.detect_cpu_limit", return_value=4),
            patch("src.config.cpu_limits.cv2"),
        ):
            apply_cpu_thread_limit()

        # Then
        assert cpu_limits.os.environ["PADDLE_PDX_CPU_NUM_THREADS"] == "99"
