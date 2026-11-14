import importlib

from fastapi.testclient import TestClient


def test_api_multi_file_deduplication_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("DEDUPFS_STORE", str(tmp_path / "storage"))
    monkeypatch.setenv("DEDUPFS_MOUNTPOINT", str(tmp_path / "mountpoint"))

    import api.main as api_main

    api_main = importlib.reload(api_main)
    client = TestClient(api_main.app)
    content = b"shared content" * 8

    response = client.post(
        "/api/files/upload",
        files=[
            ("files", ("first.txt", content, "text/plain")),
            ("files", ("second.txt", content, "text/plain")),
        ],
    )
    assert response.status_code == 200
    assert client.get("/api/dashboard").json()["total_files"] == 2
    assert client.get("/api/chunks").json()[0]["reference_count"] == 2

    lab = client.post(
        "/api/lab/analyze",
        json={"filenames": ["first.txt", "second.txt"]},
    )
    assert lab.status_code == 200
    assert lab.json()["duplicate_chunks_detected"] == 1

    assert client.delete("/api/files/first.txt").status_code == 200
    assert client.get("/api/chunks").json()[0]["reference_count"] == 1
    assert client.get("/api/files/second.txt/download").content == content
    assert client.get("/api/activities").json()

    api_main.store.close()
