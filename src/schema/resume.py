"""简历提取结果。每个结构化字段都必须挂原文出处。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from schema.document import SourceSpan


class Education(BaseModel):
    school: str
    degree: Optional[str] = None
    major: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    evidence: List[SourceSpan] = Field(default_factory=list)


class WorkExperience(BaseModel):
    company: str
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    summary: Optional[str] = None
    evidence: List[SourceSpan] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    role: Optional[str] = None
    description: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    evidence: List[SourceSpan] = Field(default_factory=list)


class Skill(BaseModel):
    name: str
    level: Optional[str] = Field(default=None, description="模型对熟练度的判断，可为空")
    evidence: List[SourceSpan] = Field(default_factory=list)


class ExtractedResume(BaseModel):
    resume_id: str
    candidate_name: Optional[str] = None
    contact: Optional[str] = None
    years_of_experience: Optional[float] = None
    educations: List[Education] = Field(default_factory=list)
    work_experiences: List[WorkExperience] = Field(default_factory=list)
    projects: List[Project] = Field(default_factory=list)
    skills: List[Skill] = Field(default_factory=list)

    def all_evidence(self) -> List[SourceSpan]:
        """收集全部出处，供 Checker 一次性校验。"""
        spans: List[SourceSpan] = []
        for group in (self.educations, self.work_experiences, self.projects, self.skills):
            for item in group:
                spans.extend(item.evidence)
        return spans
