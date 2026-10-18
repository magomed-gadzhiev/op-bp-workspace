"""Pydantic models for the R2 file structure (manifest, entity, task, process)."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG_RE = re.compile(r"^[a-z0-9]$|^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
VersionStatus = Literal["draft", "testing", "published", "archived"]


def _validate_slug(value: str) -> str:
    if not SLUG_RE.match(value):
        raise ValueError(
            "slug must match [a-z0-9][a-z0-9-]*[a-z0-9] (lowercase alnum and hyphens)"
        )
    return value


class _SluggedBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return _validate_slug(v)


class Manifest(_SluggedBase):
    name: str
    description: str = ""
    version: int = Field(ge=1)
    status: VersionStatus
    owner: str | None = None


class Entity(_SluggedBase):
    name: str
    fields: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class Task(_SluggedBase):
    title: str
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)


# Scripts have a simpler lifecycle than BP versions: no testing/published states
# (those live on BusinessProcessVersion). Mirrors backend ScriptStatus choices.
ScriptStatus = Literal["draft", "active", "archived"]
SCRIPT_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class Script(BaseModel):
    """Script attached to a BP. Round-tripped as <name>.py + <name>.meta.yaml."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str  # ASCII snake_case slug, unique within BP
    display_name: str = ""
    description: str = ""
    status: ScriptStatus = "draft"
    code: str = ""
    requirements: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not SCRIPT_NAME_RE.match(v):
            raise ValueError(
                "script name must match [a-z_][a-z0-9_]* (ascii snake_case)"
            )
        return v

    @model_validator(mode="after")
    def _default_display(self) -> "Script":
        if not self.display_name:
            self.display_name = self.name
        return self


class Process(BaseModel):
    """In-memory representation of a process directory."""
    model_config = ConfigDict(extra="forbid")

    manifest: Manifest
    entities: list[Entity] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    scripts: list[Script] = Field(default_factory=list)
