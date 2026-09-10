from src.config import memory_limits
from src.config.memory_limits import detect_memory_limit_mib


class TestDetectMemoryLimitCgroupV2:
    def test_reads_limit_in_bytes(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "memory.max"
        cgroup_file.write_text("12884901888")  # 12 GiB
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", cgroup_file)

        # When / Then
        assert detect_memory_limit_mib() == 12288.0

    def test_unlimited_falls_through(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "memory.max"
        cgroup_file.write_text("max")
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", cgroup_file)
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", tmp_path / "missing-v1")

        # When / Then
        assert detect_memory_limit_mib() is None

    def test_missing_file_falls_through(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "does-not-exist")
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", tmp_path / "missing-v1")

        # When / Then
        assert detect_memory_limit_mib() is None

    def test_malformed_content_falls_through(self, tmp_path, monkeypatch):
        # Given
        cgroup_file = tmp_path / "memory.max"
        cgroup_file.write_text("not-a-number")
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", cgroup_file)
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", tmp_path / "missing-v1")

        # When / Then
        assert detect_memory_limit_mib() is None


class TestDetectMemoryLimitCgroupV1:
    def test_reads_limit_in_bytes(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "no-v2-file")
        limit_file = tmp_path / "memory.limit_in_bytes"
        limit_file.write_text("536870912\n")  # 512 MiB
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", limit_file)

        # When / Then
        assert detect_memory_limit_mib() == 512.0

    def test_unlimited_sentinel_falls_through(self, tmp_path, monkeypatch):
        # Given — the classic cgroup v1 "no limit" value, 2^63 rounded to the page size
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "no-v2-file")
        limit_file = tmp_path / "memory.limit_in_bytes"
        limit_file.write_text("9223372036854771712")
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", limit_file)

        # When / Then
        assert detect_memory_limit_mib() is None

    def test_malformed_content_falls_through(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "no-v2-file")
        limit_file = tmp_path / "memory.limit_in_bytes"
        limit_file.write_text("garbage")
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", limit_file)

        # When / Then
        assert detect_memory_limit_mib() is None


class TestDetectMemoryLimitNoCgroup:
    def test_returns_none_when_no_cgroup_files_exist(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(memory_limits, "_CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "no-v2-file")
        monkeypatch.setattr(memory_limits, "_CGROUP_V1_MEMORY_LIMIT_PATH", tmp_path / "no-v1-file")

        # When / Then
        assert detect_memory_limit_mib() is None
