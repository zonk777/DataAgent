from app.db import initialize_database
from app.config import get_settings
from app.services.datasets import (
    chunk_upload_status,
    complete_chunk_upload,
    dataset_quality,
    get_dataset,
    import_dataset_content,
    save_upload_chunk,
)


def test_default_upload_limit_is_100mb() -> None:
    assert get_settings().max_upload_mb == 100


def test_rejects_file_larger_than_configured_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    content = b"a" * (1024 * 1024 + 1)

    try:
        import_dataset_content("too_large.csv", content, "超限测试", "")
    except ValueError as exc:
        assert "1MB" in str(exc)
    else:
        raise AssertionError("超出上传大小限制时应抛出 ValueError")


def test_chunked_dataset_upload_creates_dataset() -> None:
    initialize_database()
    content = "日期,地区,销售额\n2026-06-01,华东,123.45\n".encode("utf-8")
    chunks = [content[:12], content[12:]]
    upload_id = "testupload01"

    for index, chunk in enumerate(chunks):
        result = save_upload_chunk(
            upload_id=upload_id,
            chunk_index=index,
            total_chunks=len(chunks),
            total_size=len(content),
            filename="sales.csv",
            content=chunk,
        )
        assert index in result["received_chunks"]

    status = chunk_upload_status(upload_id)
    assert status["received_chunks"] == [0, 1]
    assert status["received_count"] == 2
    assert status["total_chunks"] == 2
    assert status["missing_chunks"] == []
    assert status["complete"] is True
    assert status["progress_percent"] == 100
    dataset = complete_chunk_upload(
        upload_id=upload_id,
        filename="sales.csv",
        total_chunks=len(chunks),
        total_size=len(content),
        name="销售测试",
        description="分片上传测试",
    )

    assert dataset["name"] == "销售测试"
    assert dataset["row_count"] == 1
    assert dataset["column_count"] == 3


def test_chunk_upload_status_reports_missing_chunks() -> None:
    initialize_database()
    upload_id = "testupload02"
    result = save_upload_chunk(
        upload_id=upload_id,
        chunk_index=1,
        total_chunks=3,
        total_size=9,
        filename="partial.csv",
        content=b"bbb",
    )

    assert result["complete"] is False
    status = chunk_upload_status(upload_id)
    assert status["received_chunks"] == [1]
    assert status["missing_chunks"] == [0, 2]
    assert status["progress_percent"] == 33.33
    assert status["complete"] is False


def test_dataset_preview_returns_first_100_rows() -> None:
    initialize_database()
    dataset = get_dataset(1)

    assert len(dataset["preview"]) == 100


def test_dataset_quality_reports_missing_duplicates_outliers_and_score() -> None:
    initialize_database()
    content = "\n".join(
        [
            "id,amount,region",
            "1,10,华东",
            "2,10,华南",
            "2,10,华南",
            "3,,华北",
            "4,1000,西南",
        ]
    ).encode("utf-8")
    dataset = import_dataset_content("quality.csv", content, "质量测试", "")

    quality = dataset_quality(dataset["id"])

    assert quality["quality_score"] < 100
    assert quality["quality_level"] in {"优秀", "良好", "一般", "较差"}
    assert quality["duplicate_rows"] == 1
    assert any(item["column"] == "amount" and item["missing_count"] == 1 for item in quality["missing"])
    assert any(item["column"] == "amount" and item["outlier_count"] >= 1 for item in quality["outliers"])
    assert quality["duplicate_values"]
