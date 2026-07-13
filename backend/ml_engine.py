from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import Evaluation, Question


CONCEPT_RUBRICS = {
    "architecture": "components interfaces data flow scalability reliability deployment boundaries",
    "technical decisions": "alternatives constraints trade offs reason selection limitations architecture",
    "personal contribution": "specific ownership individual implementation collaboration responsibility contribution",
    "problem solving": "problem diagnosis hypothesis debugging evidence solution verification learning",
    "challenges and results": "challenge constraint action measurable result baseline validation outcome",
    "impact measurement": "baseline metric measurement experiment comparison result validation percentage",
    "collaboration": "stakeholders communication feedback code review conflict decision teamwork",
    "practical depth": "implementation tools limitations internals debugging production example",
}


def _rubric_for(question: Question) -> dict[str, str]:
    selected = {
        name: text
        for name, text in CONCEPT_RUBRICS.items()
        if name in question.focus.lower() or any(token in question.question.lower() for token in name.split())
    }
    if question.item_type == "project":
        selected.update({key: CONCEPT_RUBRICS[key] for key in ("technical decisions", "personal contribution", "challenges and results")})
    elif question.item_type == "experience":
        selected.update({key: CONCEPT_RUBRICS[key] for key in ("personal contribution", "collaboration", "impact measurement")})
    else:
        selected.update({key: CONCEPT_RUBRICS[key] for key in ("practical depth", "technical decisions")})
    return selected


def concept_coverage(question: Question, answer: str) -> tuple[int, list[str]]:
    rubrics = _rubric_for(question)
    if not answer.strip() or not rubrics:
        return 0, list(rubrics)
    names = list(rubrics)
    documents = [answer] + [rubrics[name] for name in names]
    try:
        matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform(documents)
    except ValueError:
        return 0, names
    similarities = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    lexical = []
    answer_terms = set(re.findall(r"[a-zA-Z][a-zA-Z-]+", answer.lower()))
    for name in names:
        rubric_terms = set(re.findall(r"[a-zA-Z][a-zA-Z-]+", rubrics[name].lower()))
        lexical.append(len(answer_terms & rubric_terms) / max(1, min(5, len(rubric_terms))))
    combined = [min(1.0, similarity * 2.8 + overlap * 0.65) for similarity, overlap in zip(similarities, lexical)]
    score = round(100 * sum(combined) / len(combined))
    missing = [name for name, value in zip(names, combined) if value < 0.32]
    return max(0, min(100, score)), missing


def enrich_evaluation(evaluation: Evaluation, question: Question, answer: str) -> Evaluation:
    coverage, gaps = concept_coverage(question, answer)
    word_count = len(answer.split())
    confidence = min(96, round(35 + min(word_count, 120) * 0.35 + coverage * 0.25))
    blended_score = round(evaluation.score * 0.82 + coverage * 0.18)
    concepts = list(dict.fromkeys([*evaluation.concepts_to_revise, *gaps]))[:8]
    missing = list(evaluation.missing_points)
    if gaps:
        missing.append("Strengthen the answer with evidence for: " + ", ".join(gaps[:3]) + ".")
    label = "Strong" if blended_score >= 75 else "Okay" if blended_score >= 48 else "Weak"
    return evaluation.model_copy(
        update={
            "score": blended_score,
            "label": label,
            "concept_coverage": coverage,
            "confidence": confidence,
            "concepts_to_revise": concepts,
            "missing_points": list(dict.fromkeys(missing)),
        }
    )


def mastery_dashboard(rows: Iterable[dict]) -> dict:
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"total": 0, "scores": [], "coverage": []})
    total = answered = 0
    all_scores: list[int] = []
    for row in rows:
        total += 1
        key = (row["item_type"], row["item_name"])
        groups[key]["total"] += 1
        if row["score"] is not None:
            score = int(row["score"])
            groups[key]["scores"].append(score)
            groups[key]["coverage"].append(int(row["concept_coverage"] or 0))
            all_scores.append(score)
            answered += 1
    areas = []
    for (item_type, item_name), values in groups.items():
        scores = values["scores"]
        # Empirical-Bayes smoothing prevents one lucky answer from reading as mastery.
        successes = sum(score / 100 for score in scores)
        posterior = (1.4 + successes) / (3.4 + len(scores))
        mastery = round(posterior * 100) if scores else 0
        confidence = round(100 * (1 - math.exp(-len(scores) / 3))) if scores else 0
        coverage = round(sum(values["coverage"]) / len(values["coverage"])) if values["coverage"] else 0
        areas.append({
            "item_type": item_type,
            "item_name": item_name,
            "total": values["total"],
            "answered": len(scores),
            "average_score": round(sum(scores) / len(scores)) if scores else 0,
            "mastery": mastery,
            "confidence": confidence,
            "concept_coverage": coverage,
            "readiness": "ready" if mastery >= 72 and confidence >= 45 else "developing" if scores else "not_started",
        })
    areas.sort(key=lambda area: (area["mastery"] if area["answered"] else -1, area["item_name"]))
    return {
        "total_questions": total,
        "answered": answered,
        "average_score": round(sum(all_scores) / len(all_scores)) if all_scores else 0,
        "readiness_score": round(sum(area["mastery"] for area in areas) / len(areas)) if areas else 0,
        "areas": areas,
    }


def choose_adaptive_question(rows: list[dict]) -> int | None:
    if not rows:
        return None
    weighted: list[tuple[int, float]] = []
    for row in rows:
        score = row["score"]
        difficulty_weight = {"foundation": 1.1, "applied": 1.0, "deep-dive": 0.9}.get(row["difficulty"], 1.0)
        weakness = 1.5 if score is None else max(0.15, (105 - int(score)) / 70)
        novelty = 2.2 if score is None else 0.65
        weighted.append((int(row["question_id"]), difficulty_weight * weakness * novelty))
    return random.choices([item[0] for item in weighted], weights=[item[1] for item in weighted], k=1)[0]
