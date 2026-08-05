from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    keywords: list[str]
    body: str


def load_skills(skills_dir: Path) -> list[Skill]:
    skills = []
    for path in sorted(skills_dir.glob("*.md")):
        raw = path.read_text()
        if not raw.startswith("---"):
            continue  # not a skill file (e.g. skills/README.md)
        parts = raw.split("---", 2)
        if len(parts) < 3:
            logger.warning("%s: missing YAML frontmatter, skipping", path.name)
            continue
        _, fm_text, body = parts
        try:
            fm = yaml.safe_load(fm_text) or {}
            skills.append(Skill(
                name=fm["name"],
                description=fm["description"],
                keywords=fm.get("keywords", []),
                body=body.strip(),
            ))
        except (yaml.YAMLError, KeyError) as e:
            logger.warning("%s: invalid frontmatter (%s), skipping", path.name, e)
    return skills


def match_skills(query: str, skills: list[Skill], max_matches: int = 2) -> list[Skill]:
    q = query.lower()
    q_words = set(q.split())
    scored = []
    for s in skills:
        score = sum(2 for kw in s.keywords if kw.lower() in q)
        score += len(set(s.description.lower().split()) & q_words)
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_matches]]
