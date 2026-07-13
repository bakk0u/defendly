import os
import tempfile
import uuid

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()
os.environ["DATABASE_PATH"] = temp_db.name
os.environ["OLLAMA_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret-key"

from fastapi.testclient import TestClient

from backend.main import app


SAMPLE_CV = """Maya Chen
Computer Science Student
PROJECTS
StudySync AI - Built a retrieval assistant using Python, FastAPI, React and Ollama. Improved grounded answer accuracy by 18% over 120 answers.
TECHNICAL SKILLS
Python, FastAPI, React, SQL, Docker, Git, Ollama
"""


def test_authenticated_cv_to_realtime_ready_flow():
    with TestClient(app) as client:
        email = f"maya-{uuid.uuid4()}@example.com"
        registered = client.post("/api/auth/register", json={"name": "Maya Chen", "email": email, "password": "strong-password"})
        assert registered.status_code == 201
        token = registered.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/api/cvs/extract", data={"cv_text": SAMPLE_CV, "provider": "fallback"}, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["extraction"]["projects"]
        assert len(payload["questions"]) >= 5

        question = payload["questions"][0]
        evaluated = client.post(
            "/api/evaluations",
            headers=headers,
            json={
                "question_id": question["id"],
                "provider": "fallback",
                "answer": "I built the FastAPI service in Python, used Ollama for local inference, tested 120 answers, and improved grounded accuracy by 18% after adding citation checks.",
            },
        )
        assert evaluated.status_code == 200
        assert evaluated.json()["label"] in {"Weak", "Okay", "Strong"}
        assert 0 <= evaluated.json()["concept_coverage"] <= 100

        dashboard = client.get(f"/api/cvs/{payload['cv_id']}/dashboard", headers=headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["answered"] == 1
        assert "readiness_score" in dashboard.json()

        providers = client.get("/api/providers", headers=headers)
        assert providers.status_code == 200
        assert {item["id"] for item in providers.json()} >= {"ollama", "openai", "anthropic", "gemini", "fallback"}

        with client.websocket_connect(f"/ws/interview/{payload['cv_id']}?token={token}&provider=fallback") as socket:
            question_event = socket.receive_json()
            assert question_event["type"] == "question"
            socket.send_json({
                "type": "answer",
                "answer": "I owned the Python API and citation checks, compared results against a baseline set of 120 answers, and documented the trade-off between latency and grounded accuracy.",
            })
            assert socket.receive_json()["type"] == "status"
            assert socket.receive_json()["type"] == "evaluation"
