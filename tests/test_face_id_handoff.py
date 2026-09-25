from .conftest import DOC_NUMBER, headers, scan_body


def test_face_id_handoff_object(client, worker_stub):
    created = client.post("/v1/documents/scan", json=scan_body(), headers=headers()).json()
    scan_id = created["scan_id"]
    pending = client.get(f"/v1/documents/{scan_id}/face-id-handoff", headers=headers())
    assert pending.status_code == 200
    assert pending.json()["ready"] is False

    client.post(f"/v1/documents/{scan_id}/confirm", json={}, headers=headers())
    r = client.get(f"/v1/documents/{scan_id}/face-id-handoff", headers=headers())
    assert r.status_code == 200
    body = r.json()
    assert body["schema_ref"] == "codestra.document.face-id-handoff/v1"
    assert body["ready"] is True and body["status"] == "confirmed"
    assert body["tenant_id"] == "tenant-a"
    assert body["subject"]["given_names"] == "MARIA ELENA"
    assert body["subject"]["date_of_birth"] == "1990-04-12"
    assert body["document"]["number_last4"] == "5678"
    assert body["portrait_detected"] is True and body["portrait_side"] == "front"
    assert body["front_image_sha256"] == created["images"][0]["sha256"]
    assert body["verification"]["authenticity_verified"] is False
    assert DOC_NUMBER not in r.text
    # FACE-ID is never called: the only outbound traffic was the single OCR call.
    assert [req.url.path for req in worker_stub.requests] == ["/v1/ocr/extract"]
