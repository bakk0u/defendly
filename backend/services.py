from __future__ import annotations

import json
import re
from collections import Counter

from langchain_core.prompts import ChatPromptTemplate

from .models import EducationItem, Evaluation, ExperienceItem, ExtractedCV, ProjectItem, Question, RiskyClaim
from .providers import LLMProvider, OllamaClient


TECH_TERMS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Vue", "Angular",
    "FastAPI", "Flask", "Django", "Node.js", "Express", "SQL", "SQLite",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Docker", "Kubernetes", "Git",
    "GitHub Actions", "AWS", "Azure", "GCP", "Linux", "Pandas", "NumPy",
    "scikit-learn", "PyTorch", "TensorFlow", "LangChain", "Ollama", "REST",
    "GraphQL", "Power BI", "Tableau", "Spark", "Kafka", "HTML", "CSS",
]


STRUCTURED_PROMPT = ChatPromptTemplate.from_messages(
    [("system", "{system}"), ("human", "{prompt}")]
)


async def run_structured_chain(
    client: LLMProvider,
    system: str,
    prompt: str,
    schema: dict,
) -> dict | None:
    """Use LangChain for prompt composition while providers own transport and JSON mode."""
    prompt_value = await STRUCTURED_PROMPT.ainvoke({"system": system, "prompt": prompt})
    messages = prompt_value.to_messages()
    return await client.structured(str(messages[0].content), str(messages[-1].content), schema)


def _lines(text: str) -> list[str]:
    return [re.sub(r"^[\s•●▪◦*\-–—]+", "", line).strip() for line in text.splitlines() if line.strip()]


def _sections(text: str) -> dict[str, list[str]]:
    aliases = {
        "education": "education", "academic": "education",
        "experience": "experience", "work experience": "experience", "employment": "experience",
        "projects": "projects", "project": "projects",
        "skills": "skills", "technical skills": "skills", "technologies": "skills",
    }
    sections: dict[str, list[str]] = {"other": []}
    active = "other"
    for line in _lines(text):
        heading = re.sub(r"[:|]", "", line).strip().lower()
        if heading in aliases:
            active = aliases[heading]
            sections.setdefault(active, [])
        else:
            sections.setdefault(active, []).append(line)
    return sections


def fallback_extract(text: str) -> ExtractedCV:
    lines = _lines(text)
    sections = _sections(text)
    first = lines[0] if lines and len(lines[0].split()) <= 6 else "Candidate"
    found_skills = [term for term in TECH_TERMS if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I)]
    metrics = list(dict.fromkeys(re.findall(r"\b(?:\d+(?:\.\d+)?%|\d+[xX]|\d+[+]?(?:\s*(?:users|records|requests|customers|hours|days|models|features)))\b", text, re.I)))

    project_lines = sections.get("projects", [])
    projects: list[ProjectItem] = []
    for line in project_lines[:8]:
        if len(line) < 4:
            continue
        name, _, description = re.split(r"\s[-–—:|]\s|:\s*", line, maxsplit=1)[0], "", ""
        parts = re.split(r"\s[-–—:|]\s|:\s*", line, maxsplit=1)
        name = parts[0][:100]
        description = parts[1] if len(parts) > 1 else line
        tech = [term for term in found_skills if term.lower() in line.lower()]
        line_metrics = [metric for metric in metrics if metric.lower() in line.lower()]
        projects.append(ProjectItem(name=name, description=description, technologies=tech, metrics=line_metrics))
    if not projects:
        project_like = [line for line in lines if re.search(r"\b(built|developed|implemented|created|designed|trained)\b", line, re.I)]
        for index, line in enumerate(project_like[:4], 1):
            projects.append(ProjectItem(name=f"CV Project {index}", description=line, technologies=[t for t in found_skills if t.lower() in line.lower()]))

    experiences: list[ExperienceItem] = []
    for line in sections.get("experience", []):
        parts = [part.strip() for part in re.split(r"\s*[|•]\s*", line) if part.strip()]
        is_heading = len(parts) >= 2 and (
            len(line) < 150 or bool(re.search(r"\b(?:intern|engineer|developer|analyst|assistant|manager|consultant|researcher)\b", line, re.I))
        )
        if is_heading:
            period = next((part for part in parts if re.search(r"\b(?:19|20)\d{2}\b|present", part, re.I)), "")
            non_period = [part for part in parts if part != period]
            role = non_period[0]
            company = non_period[1] if len(non_period) > 1 else "Organization"
            experiences.append(ExperienceItem(company=company, role=role, period=period))
        elif experiences:
            experiences[-1].achievements.append(line)
            experiences[-1].technologies.extend(t for t in found_skills if t.lower() in line.lower() and t not in experiences[-1].technologies)

    education: list[EducationItem] = []
    for line in sections.get("education", []):
        parts = [part.strip() for part in re.split(r"\s*[|•]\s*", line) if part.strip()]
        if not parts:
            continue
        period = next((part for part in parts if re.search(r"\b(?:19|20)\d{2}\b|present", part, re.I)), "")
        non_period = [part for part in parts if part != period]
        degree = non_period[0]
        institution = non_period[1] if len(non_period) > 1 else "Institution"
        education.append(EducationItem(institution=institution, degree=degree, period=period))

    risky: list[RiskyClaim] = []
    for line in lines:
        if re.search(r"\b(led|optimized|improved|increased|reduced|architected|expert|advanced|responsible for)\b", line, re.I) or any(m.lower() in line.lower() for m in metrics):
            risky.append(RiskyClaim(
                claim=line[:240],
                risk="high" if any(m.lower() in line.lower() for m in metrics) else "medium",
                reason="An interviewer is likely to ask how this was measured and what you personally contributed.",
                prepare="Prepare the baseline, your exact actions, trade-offs, and evidence for the result.",
            ))

    return ExtractedCV(
        candidate_name=first,
        headline=lines[1] if len(lines) > 1 else "",
        education=education,
        work_experience=experiences,
        projects=projects,
        technical_skills=found_skills,
        tools_frameworks=[s for s in found_skills if s not in {"Python", "Java", "JavaScript", "TypeScript", "SQL", "HTML", "CSS"}],
        metrics=metrics,
        risky_claims=risky[:8],
    )


async def extract_cv(text: str, client: LLMProvider) -> tuple[ExtractedCV, str]:
    system = "You extract only facts explicitly present in a CV. Never invent employers, metrics, tools, or project details. Return JSON matching the schema."
    prompt = f"Extract this CV for interview preparation. Flag broad, quantified, leadership, or technically deep claims that need defending.\n\nCV:\n{text[:24000]}"
    data = await run_structured_chain(client, system, prompt, ExtractedCV.model_json_schema())
    if data:
        try:
            return ExtractedCV.model_validate(data), client.display_model
        except ValueError:
            pass
    return fallback_extract(text), "deterministic fallback"


def fallback_questions(cv_id: int, cv: ExtractedCV) -> list[Question]:
    questions: list[Question] = []
    templates = [
        ("Give me the 90-second overview of {name}: the problem, your role, and the outcome.", "structured overview", "foundation"),
        ("Walk me through the architecture and technical choices behind {name}. Why those choices?", "technical decisions", "applied"),
        ("What was the hardest challenge in {name}, and how did you diagnose and solve it?", "problem solving", "applied"),
        ("What did you personally implement in {name}, and what was done by teammates or existing tools?", "personal contribution", "deep-dive"),
        ("If you rebuilt {name} today, what would you change and how would you measure success?", "reflection and metrics", "deep-dive"),
    ]
    for project in cv.projects:
        for template, focus, difficulty in templates:
            questions.append(Question(cv_id=cv_id, item_type="project", item_name=project.name, question=template.format(name=project.name), focus=focus, difficulty=difficulty))
    for exp in cv.work_experience:
        for question, focus in [
            (f"Which result at {exp.company} are you most proud of, and what was your direct contribution?", "ownership and impact"),
            (f"Describe a difficult trade-off you made while working as {exp.role}.", "decision making"),
            (f"How did you collaborate, receive feedback, and communicate progress at {exp.company}?", "collaboration"),
        ]:
            questions.append(Question(cv_id=cv_id, item_type="experience", item_name=exp.company, question=question, focus=focus))
    for skill in cv.technical_skills[:12]:
        questions.append(Question(cv_id=cv_id, item_type="skill", item_name=skill, question=f"You list {skill} on your CV. Where did you use it, what did you build, and what are its limitations?", focus="practical depth"))
    return questions


async def generate_questions(cv_id: int, cv: ExtractedCV, client: LLMProvider) -> list[Question]:
    fallback = fallback_questions(cv_id, cv)
    if not cv.projects and not cv.work_experience and not cv.technical_skills:
        return fallback
    schema = {"type": "object", "properties": {"questions": {"type": "array", "items": Question.model_json_schema()}}, "required": ["questions"]}
    prompt = "Generate exactly five probing questions for every project, and useful questions for experiences and skills. Questions must test personal contribution, decisions, trade-offs, challenges, results, and technical depth.\n\nCV JSON:\n" + cv.model_dump_json()
    data = await run_structured_chain(client, "You are a rigorous internship interviewer. Return only schema-valid JSON.", prompt, schema)
    if data:
        try:
            parsed = [Question.model_validate({**q, "cv_id": cv_id, "id": None}) for q in data.get("questions", [])]
            project_counts = Counter(q.item_name for q in parsed if q.item_type == "project")
            if all(project_counts[p.name] >= 5 for p in cv.projects):
                return parsed
        except ValueError:
            pass
    return fallback


def heuristic_evaluation(question: Question, answer: str) -> Evaluation:
    words = answer.split()
    lower = answer.lower()
    has_numbers = bool(re.search(r"\b\d+(?:\.\d+)?%?\b", answer))
    has_first_person = bool(re.search(r"\b(i|my|me)\b", lower))
    has_tools = any(term.lower() in lower for term in TECH_TERMS)
    has_challenge = any(term in lower for term in ["challenge", "problem", "issue", "failed", "constraint", "trade-off", "tradeoff"])
    has_result = any(term in lower for term in ["result", "improved", "reduced", "increased", "achieved", "outcome", "measured"])
    length_score = min(20, max(4, len(words) // 5))
    criteria = {
        "clarity": min(20, length_score + (3 if len(words) >= 45 else 0)),
        "technical_accuracy": min(20, 8 + (7 if has_tools else 0) + (3 if len(words) >= 55 else 0)),
        "personal_contribution": 18 if has_first_person else 6,
        "tools_and_decisions": 17 if has_tools else 6,
        "challenges_and_results": min(20, 5 + (6 if has_challenge else 0) + (5 if has_result else 0) + (4 if has_numbers else 0)),
    }
    score = min(100, sum(criteria.values()))
    missing: list[str] = []
    concepts: list[str] = []
    if not has_first_person:
        missing.append("Separate your personal contribution from the team's work.")
    if not has_tools:
        missing.append("Name the concrete tools, methods, or technical decisions you used.")
    if not has_challenge:
        missing.append("Explain one meaningful challenge or trade-off.")
        concepts.append("technical trade-offs")
    if not has_result or not has_numbers:
        missing.append("Close with a measurable or observable result and how it was validated.")
        concepts.append("impact measurement")
    if len(words) < 45:
        missing.append("Add enough context to make the answer understandable without the CV.")
        concepts.append("STAR answer structure")
    label = "Strong" if score >= 75 else "Okay" if score >= 48 else "Weak"
    improved = (
        f"For {question.item_name}, I would start by stating the problem and why it mattered. "
        "I would then describe my specific responsibility, the technical approach and tools I selected, "
        "and the reason for the most important trade-off. I would explain one challenge, the action I took "
        "to resolve it, and finish with a measured result plus what I learned or would improve next time."
    )
    return Evaluation(
        label=label, score=score,
        summary=f"{label} answer: the foundation is present, but the response should make your evidence and ownership easier to verify.",
        criteria=criteria, missing_points=missing or ["Add one sharper technical trade-off to make the answer more distinctive."],
        concepts_to_revise=list(dict.fromkeys(concepts)) or [question.focus], improved_answer=improved,
    )


async def evaluate_answer(question: Question, answer: str, client: LLMProvider) -> Evaluation:
    schema = Evaluation.model_json_schema()
    prompt = f"Question: {question.question}\nCV item: {question.item_name}\nFocus: {question.focus}\nCandidate answer: {answer}\n\nScore rigorously. Do not credit facts not stated. Improved answer must preserve truth and use placeholders instead of invented metrics."
    data = await run_structured_chain(client, "You evaluate internship interview answers for clarity, technical accuracy, ownership, tools, challenges, and results. Return schema-valid JSON.", prompt, schema)
    if data:
        try:
            return Evaluation.model_validate(data)
        except ValueError:
            pass
    return heuristic_evaluation(question, answer)
