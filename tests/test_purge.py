from pathlib import Path

import pytest

from recon.purge import purge_expired_uploads

CUTOFF = "2021-01-01T00:00:00+00:00"


def _record(record_id, storage_key, purge_after, purged=False):
    return {
        "id": record_id,
        "firm_id": 42,
        "storage_key": storage_key,
        "purge_after": purge_after,
        "purged": purged,
    }


def test_expired_file_is_deleted_and_marked_purged(tmp_path):
    storage = tmp_path / "storage"
    (storage / "firm42").mkdir(parents=True)
    target = storage / "firm42" / "upload.bin"
    target.write_bytes(b"x" * 100)

    records = [_record("u1", "firm42/upload.bin", "2020-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(records, storage, cutoff_iso=CUTOFF)

    assert purged == 1
    assert not target.exists()
    assert updated[0]["purged"] is True
    assert updated[0]["storage_key"] is None
    assert updated[0]["purged_at"]
    assert audits[0]["verb"] == "purge"
    assert audits[0]["meta"]["bytes_freed"] == 100
    assert audits[0]["object"] == "upload:u1"


def test_future_records_are_left_alone(tmp_path):
    storage = tmp_path / "storage"
    (storage / "firm42").mkdir(parents=True)
    target = storage / "firm42" / "upload.bin"
    target.write_bytes(b"x" * 10)

    records = [_record("u1", "firm42/upload.bin", "2022-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(records, storage, cutoff_iso=CUTOFF)

    assert purged == 0
    assert target.exists()
    assert updated[0]["purged"] is False
    assert audits == []


def test_already_purged_records_are_untouched(tmp_path):
    records = [_record("u1", "gone/already.bin", "2020-01-01T00:00:00+00:00", purged=True)]
    purged, updated, audits = purge_expired_uploads(records, tmp_path, cutoff_iso=CUTOFF)
    assert purged == 0
    assert updated[0] == records[0]
    assert audits == []


def test_records_without_expiry_are_untouched(tmp_path):
    records = [_record("u1", "firm42/upload.bin", None), _record("u2", "firm42/upload.bin", "")]
    purged, updated, audits = purge_expired_uploads(records, tmp_path, cutoff_iso=CUTOFF)
    assert purged == 0
    assert updated == records
    assert audits == []


def test_missing_file_is_marked_purged_without_bytes(tmp_path):
    records = [_record("u1", "firm42/never-existed.bin", "2020-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(records, tmp_path / "storage", cutoff_iso=CUTOFF)
    assert purged == 1
    assert updated[0]["purged"] is True
    assert audits[0]["verb"] == "purge"
    assert audits[0]["meta"]["bytes_freed"] == 0


def test_unparseable_timestamp_is_skipped_with_audit(tmp_path):
    storage = tmp_path / "storage"
    (storage / "firm42").mkdir(parents=True)
    target = storage / "firm42" / "upload.bin"
    target.write_bytes(b"x" * 10)

    records = [_record("u1", "firm42/upload.bin", "not-a-date")]
    purged, updated, audits = purge_expired_uploads(records, storage, cutoff_iso=CUTOFF)

    assert purged == 0
    assert target.exists()
    assert updated[0]["purged"] is False
    assert updated[0]["storage_key"] == "firm42/upload.bin"
    assert audits[0]["verb"] == "purge_skip"
    assert "parseable" in audits[0]["meta"]["reason"]


def test_traversal_storage_key_is_skipped(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")

    records = [_record("u1", "../outside.txt", "2020-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(records, storage, cutoff_iso=CUTOFF)

    assert purged == 0
    assert outside.exists()
    assert updated[0]["purged"] is False
    assert updated[0]["storage_key"] == "../outside.txt"
    assert audits[0]["verb"] == "purge_skip"
    assert "escapes" in audits[0]["meta"]["reason"]


def test_absolute_storage_key_is_skipped(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")

    records = [_record("u1", str(outside), "2020-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(records, storage, cutoff_iso=CUTOFF)

    assert purged == 0
    assert outside.exists()
    assert audits[0]["verb"] == "purge_skip"


def test_failed_deletion_is_not_marked_purged(tmp_path, monkeypatch):
    storage = tmp_path / "storage" / "firm42"
    storage.mkdir(parents=True)
    target = storage / "upload.bin"
    target.write_bytes(b"x" * 10)

    def boom(self, missing=None):
        raise OSError("file is locked")

    monkeypatch.setattr(Path, "unlink", boom)
    records = [_record("u1", "firm42/upload.bin", "2020-01-01T00:00:00+00:00")]
    purged, updated, audits = purge_expired_uploads(
        records, tmp_path / "storage", cutoff_iso=CUTOFF
    )

    assert purged == 0
    assert target.exists()
    assert updated[0]["purged"] is False
    assert updated[0]["storage_key"] == "firm42/upload.bin"
    assert audits[0]["verb"] == "purge_failed"
    assert "locked" in audits[0]["meta"]["reason"]


def test_naive_timestamps_are_treated_as_utc(tmp_path):
    records = [_record("u1", None, "2020-06-15")]
    purged, updated, audits = purge_expired_uploads(records, tmp_path, cutoff_iso=CUTOFF)
    assert purged == 1
    assert updated[0]["purged"] is True


def test_invalid_cutoff_raises(tmp_path):
    with pytest.raises(ValueError):
        purge_expired_uploads([], tmp_path, cutoff_iso="yesterday-ish")
