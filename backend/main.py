from __future__ import annotations

import io
import json
import os
import random
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pypdf import PdfReader

from . import database
from .ml_engine import choose_adaptive_question, enrich_evaluation, mastery_dashboard
from .models import (
    AuthResponse,
    CVSummary,
    EvaluationRequest,
    ExtractionResponse,
    ExtractedCV,
    LoginRequest,
    ProviderInfo,
    ProviderPreference,
    Question,
    RegisterRequest,
    UserPublic,
)
from .providers import provider_registry
from .security import create_access_token, decode_access_token, hash_password, verify_password
from .services import evaluate_answer, extract_cv, generate_questions


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_database()
    yield


app = FastAPI(title="Defendly API", version="2.0.0", lifespan=lifespan)
origin_values = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:5173").split(",") if origin.strip()]
origins = [origin if origin.startswith(("http://", "https://")) else f"https://{origin}" for origin in origin_values]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer(auto_error=False)


def user_public(row: sqlite3.Row) -> UserPublic:
    return UserPublic(id=row["id"], email=row["email"], name=row["name"], preferred_provider=row["preferred_provider"])


def set_auth_cookie(response: Response, token: str) -> None:
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        "defendly_session",
        token,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        max_age=int(os.getenv("ACCESS_TOKEN_MINUTES", "10080")) * 60,
        path="/",
    )


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    defendly_session: Annotated[str | None, Cookie()] = None,
) -> sqlite3.Row:
    token = credentials.credentials if credentials else defendly_session
    payload = decode_access_token(token) if token else None
    row = database.get_user(int(payload["sub"])) if payload and str(payload.get("sub", "")).isdigit() else None
    if not row:
        raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    return row


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


@app.get("/api/health")
def health() -> dict:
    selected = provider_registry.get(None)
    return {"status": "ok", "llm": selected.id, "model": selected.model, "version": app.version}


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, response: Response):
    try:
        row = database.create_user(payload.email, payload.name, hash_password(payload.password))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "An account with this email already exists.") from exc
    token = create_access_token(row["id"], row["email"])
    set_auth_cookie(response, token)
    return AuthResponse(user=user_public(row), access_token=token)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response):
    row = database.get_user_by_email(payload.email)
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    token = create_access_token(row["id"], row["email"])
    set_auth_cookie(response, token)
    return AuthResponse(user=user_public(row), access_token=token)


@app.get("/api/auth/session", response_model=AuthResponse)
def session(user: Annotated[sqlite3.Row, Depends(current_user)], response: Response):
    token = create_access_token(user["id"], user["email"])
    set_auth_cookie(response, token)
    return AuthResponse(user=user_public(user), access_token=token)


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("defendly_session", path="/")


@app.get("/api/providers", response_model=list[ProviderInfo])
def providers(_: Annotated[sqlite3.Row, Depends(current_user)]):
    return provider_registry.infos()


@app.put("/api/settings/provider", response_model=UserPublic)
def provider_preference(payload: ProviderPreference, user: Annotated[sqlite3.Row, Depends(current_user)]):
    info = next((item for item in provider_registry.infos() if item.id == payload.provider), None)
    if not info or not info.available:
        raise HTTPException(422, "That provider is not configured on this server.")
    return user_public(database.update_user_provider(user["id"], payload.provider))


@app.get("/api/cvs", response_model=list[CVSummary])
def cvs(user: Annotated[sqlite3.Row, Depends(current_user)]):
    summaries = []
    for row in database.list_cvs(user["id"]):
        extraction = json.loads(row["extraction_json"])
        summaries.append(CVSummary(
            cv_id=row["id"], source_name=row["source_name"],
            candidate_name=extraction.get("candidate_name", "Candidate"),
            headline=extraction.get("headline", ""), project_count=row["project_count"],
            question_count=row["question_count"], created_at=row["created_at"],
        ))
    return summaries


@app.post("/api/cvs/extract", response_model=ExtractionResponse)
async def create_cv(
    user: Annotated[sqlite3.Row, Depends(current_user)],
    cv_text: str = Form(default=""),
    provider: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
):
    source_name = "Pasted CV"
    text = cv_text.strip()
    if file:
        if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF uploads are supported.")
        contents = await file.read()
        if len(contents) > 8 * 1024 * 1024:
            raise HTTPException(413, "PDF must be smaller than 8 MB.")
        try:
            text = pdf_text(contents)
        except Exception as exc:
            raise HTTPException(422, "The PDF could not be read. Try pasting the CV text instead.") from exc
        source_name = file.filename or "Uploaded CV"
    if len(text) < 80:
        raise HTTPException(422, "Add at least 80 characters of CV content.")

    llm = provider_registry.get(provider or user["preferred_provider"])
    extraction, model_used = await extract_cv(text, llm)
    cv_id = database.save_cv(user["id"], source_name, text, extraction.model_dump(), model_used)
    generated = await generate_questions(cv_id, extraction, llm)
    saved = database.save_questions(cv_id, [q.model_dump(exclude={"id", "cv_id"}) for q in generated])
    return ExtractionResponse(
        cv_id=cv_id,
        source_name=source_name,
        extraction=extraction,
        questions=[Question.model_validate(q) for q in saved],
        model_used=model_used,
    )


@app.get("/api/cvs/{cv_id}")
def read_cv(cv_id: int, user: Annotated[sqlite3.Row, Depends(current_user)]):
    row = database.get_cv(cv_id, user["id"])
    if not row:
        raise HTTPException(404, "CV not found")
    return {"cv_id": cv_id, "source_name": row["source_name"], "extraction": json.loads(row["extraction_json"]), "model_used": row["model_used"]}


@app.get("/api/cvs/{cv_id}/questions", response_model=list[Question])
def read_questions(cv_id: int, user: Annotated[sqlite3.Row, Depends(current_user)]):
    if not database.get_cv(cv_id, user["id"]):
        raise HTTPException(404, "CV not found")
    return [Question.model_validate(dict(row)) for row in database.list_questions(cv_id, user["id"])]


@app.get("/api/cvs/{cv_id}/questions/random", response_model=Question)
def random_question(cv_id: int, user: Annotated[sqlite3.Row, Depends(current_user)]):
    rows = database.list_questions(cv_id, user["id"])
    if not rows:
        raise HTTPException(404, "No questions available")
    return Question.model_validate(dict(random.choice(rows)))


@app.get("/api/cvs/{cv_id}/questions/adaptive", response_model=Question)
def adaptive_question(cv_id: int, user: Annotated[sqlite3.Row, Depends(current_user)]):
    if not database.get_cv(cv_id, user["id"]):
        raise HTTPException(404, "CV not found")
    rows = [dict(row) for row in database.dashboard_rows(cv_id, user["id"])]
    question_id = choose_adaptive_question(rows)
    row = database.get_question(question_id, user["id"]) if question_id else None
    if not row:
        raise HTTPException(404, "No questions available")
    return Question.model_validate(dict(row))


@app.post("/api/evaluations")
async def create_evaluation(payload: EvaluationRequest, user: Annotated[sqlite3.Row, Depends(current_user)]):
    row = database.get_question(payload.question_id, user["id"])
    if not row:
        raise HTTPException(404, "Question not found")
    question = Question.model_validate(dict(row))
    llm = provider_registry.get(payload.provider or user["preferred_provider"])
    evaluation = enrich_evaluation(await evaluate_answer(question, payload.answer, llm), question, payload.answer)
    attempt_id = database.save_attempt(payload.question_id, payload.answer, evaluation.model_dump(exclude={"attempt_id"}))
    return evaluation.model_copy(update={"attempt_id": attempt_id})


@app.get("/api/cvs/{cv_id}/dashboard")
def dashboard(cv_id: int, user: Annotated[sqlite3.Row, Depends(current_user)]):
    if not database.get_cv(cv_id, user["id"]):
        raise HTTPException(404, "CV not found")
    result = mastery_dashboard([dict(row) for row in database.dashboard_rows(cv_id, user["id"])])
    for area in result["areas"]:
        if area["answered"]:
            database.save_mastery(user["id"], cv_id, area["item_type"], area["item_name"], area["mastery"], area["confidence"])
    return result


def websocket_user(websocket: WebSocket) -> sqlite3.Row | None:
    token = websocket.query_params.get("token") or websocket.cookies.get("defendly_session")
    payload = decode_access_token(token) if token else None
    return database.get_user(int(payload["sub"])) if payload and str(payload.get("sub", "")).isdigit() else None


@app.websocket("/ws/interview/{cv_id}")
async def interview_socket(websocket: WebSocket, cv_id: int):
    user = websocket_user(websocket)
    if not user or not database.get_cv(cv_id, user["id"]):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    llm = provider_registry.get(websocket.query_params.get("provider") or user["preferred_provider"])
    session_id = database.create_chat_session(user["id"], cv_id, llm.id)

    async def send_next() -> Question | None:
        rows = [dict(row) for row in database.dashboard_rows(cv_id, user["id"])]
        question_id = choose_adaptive_question(rows)
        question_row = database.get_question(question_id, user["id"]) if question_id else None
        if not question_row:
            await websocket.send_json({"type": "error", "message": "No questions are available for this CV."})
            return None
        question = Question.model_validate(dict(question_row))
        database.save_chat_message(session_id, "assistant", question.question, {"question_id": question.id})
        await websocket.send_json({"type": "question", "question": question.model_dump(), "session_id": session_id})
        return question

    question = await send_next()
    try:
        while True:
            message = await websocket.receive_json()
            event = message.get("type")
            if event == "next":
                question = await send_next()
                continue
            if event != "answer" or not question:
                await websocket.send_json({"type": "error", "message": "Send an answer or ask for the next question."})
                continue
            answer = str(message.get("answer", "")).strip()
            if len(answer) < 10:
                await websocket.send_json({"type": "error", "message": "Add a little more detail before submitting."})
                continue
            database.save_chat_message(session_id, "user", answer, {"question_id": question.id})
            await websocket.send_json({"type": "status", "message": "Mapping your evidence against the interview rubric…"})
            evaluation = enrich_evaluation(await evaluate_answer(question, answer, llm), question, answer)
            attempt_id = database.save_attempt(question.id, answer, evaluation.model_dump(exclude={"attempt_id"}))
            evaluation = evaluation.model_copy(update={"attempt_id": attempt_id})
            database.save_chat_message(session_id, "assistant", evaluation.summary, evaluation.model_dump())
            await websocket.send_json({"type": "evaluation", "evaluation": evaluation.model_dump()})
    except WebSocketDisconnect:
        return
