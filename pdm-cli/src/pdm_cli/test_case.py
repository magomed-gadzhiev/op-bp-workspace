"""Pydantic models for processes/<bp>/tests/<case>.yaml."""

from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ruamel.yaml import YAML

DB_WHITELIST = frozenset({"process_instances", "entity_state", "assignments"})


class HttpSideEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["http"]
    method: str | None = None
    url_matches: str  # regex
    body_contains: list[str] = Field(default_factory=list)
    min_count: int = 1
    max_count: int | None = None


class SshSideEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ssh"]
    host: str | None = None
    command_matches: str
    min_count: int = 1
    max_count: int | None = None


class DbSideEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["db"]
    table: str
    where: dict[str, Any] = Field(default_factory=dict)
    exists: bool | None = None
    count: int | None = None
    min_count: int = 1
    max_count: int | None = None

    @model_validator(mode="after")
    def _whitelist(self):
        if self.table not in DB_WHITELIST:
            raise ValueError(
                f"kind:db table '{self.table}' not in whitelist "
                f"{sorted(DB_WHITELIST)} — external DBs / persistent egress "
                "logs are Etap 5+"
            )
        return self


SideEffect = Annotated[
    Union[HttpSideEffect, SshSideEffect, DbSideEffect],
    Field(discriminator="kind"),
]


class EntityBlock(BaseModel):
    """Inline entity creation: type (name or id) + fields → POST /api/entities/."""
    model_config = ConfigDict(extra="forbid")
    type: str | int  # entity_type.name (resolved) or entity_type.id
    fields: dict[str, Any] = Field(default_factory=dict)


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    final_status: Literal["completed", "cancelled", "error", "suspended"]
    side_effects: list[SideEffect] = Field(default_factory=list)


class TestCase(BaseModel):
    """One BP test case.

    Hybrid entity form (variant C): exactly one of `entity_id` or `entity`
    must be set. `entity_id` references a pre-existing entity; `entity`
    block tells the runner to create one via POST /api/entities/ before
    starting the BP.
    """
    model_config = ConfigDict(extra="forbid")
    name: str
    fixtures: list[str] = Field(default_factory=list)
    entity_id: int | None = None
    entity: EntityBlock | None = None
    additional_entities: dict[str, int] = Field(default_factory=dict)
    timeout_sec: int = 60
    expect: Expect

    @model_validator(mode="after")
    def _exactly_one_entity(self):
        has_id = self.entity_id is not None
        has_block = self.entity is not None
        if has_id == has_block:  # both or neither
            raise ValueError(
                "exactly one of `entity_id` or `entity` must be set"
            )
        return self


def load_test_case(path: Path) -> TestCase:
    y = YAML(typ="safe")
    with Path(path).open("r", encoding="utf-8") as f:
        return TestCase.model_validate(y.load(f))
