from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserPublic(BaseModel):
    id: int
    email: EmailStr
    name: str
    preferred_provider: str = "ollama"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    user: UserPublic
    access_token: str


class ProviderPreference(BaseModel):
    provider: str


class ProviderInfo(BaseModel):
    id: str
    label: str
    model: str
    available: bool
    local: bool = False


class EducationItem(BaseModel):
    institution: str
    degree: str = ""
    field: str = ""
    period: str = ""
    details: list[str] = Field(default_factory=list)


class ExperienceItem(BaseModel):
    company: str
    role: str
    period: str = ""
    achievements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)


class RiskyClaim(BaseModel):
    claim: str
    risk: Literal["low", "medium", "high"] = "medium"
    reason: str
    prepare: str


class ExtractedCV(BaseModel):
    candidate_name: str = "Candidate"
    headline: str = ""
    education: list[EducationItem] = Field(default_factory=list)
    work_experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    tools_frameworks: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    risky_claims: list[RiskyClaim] = Field(default_factory=list)


class Question(BaseModel):
    id: int | None = None
    cv_id: int
    item_type: Literal["project", "experience", "skill", "claim"]
    item_name: str
    question: str
    focus: str
    difficulty: Literal["foundation", "applied", "deep-dive"] = "applied"


class EvaluationRequest(BaseModel):
    question_id: int
    answer: str = Field(min_length=10, max_length=12000)
    provider: str | None = None


class Evaluation(BaseModel):
    attempt_id: int | None = None
    label: Literal["Weak", "Okay", "Strong"]
    score: int = Field(ge=0, le=100)
    summary: str
    criteria: dict[str, int]
    missing_points: list[str]
    concepts_to_revise: list[str]
    improved_answer: str
    concept_coverage: int = Field(default=0, ge=0, le=100)
    confidence: int = Field(default=0, ge=0, le=100)


class ExtractionResponse(BaseModel):
    cv_id: int
    source_name: str
    extraction: ExtractedCV
    questions: list[Question]
    model_used: str


class CVSummary(BaseModel):
    cv_id: int
    source_name: str
    candidate_name: str
    headline: str
    project_count: int
    question_count: int
    created_at: str
