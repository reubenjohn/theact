"""YAML serialization and deserialization for Pydantic models."""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_yaml(path: Path, model: type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return model.model_validate(data)


def load_yaml_list(path: Path, model: type[T]) -> list[T]:
    """Load a YAML file containing a list and validate each item."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    return [model.model_validate(item) for item in data]


def dump_yaml(path: Path, model: BaseModel) -> None:
    """Serialize a Pydantic model to YAML and write to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            model.model_dump(exclude_none=True),
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def dump_yaml_list(path: Path, models: list[BaseModel]) -> None:
    """Serialize a list of Pydantic models to YAML and write to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [m.model_dump(exclude_none=True) for m in models]
    with open(path, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def append_yaml_entry(path: Path, model: BaseModel) -> None:
    """Append a single model as a YAML list entry to an existing file.

    If the file doesn't exist or is empty, creates it with a single-item list.
    If the file exists, loads the list, appends, and rewrites.
    """
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or []
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = []
    data.append(model.model_dump(exclude_none=True))
    with open(path, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
