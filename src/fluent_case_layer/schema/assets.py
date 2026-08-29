"""Immutable asset lock document."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .common import (
    EnvironmentVariable,
    Identifier,
    StrictModel,
    VersionedDocument,
    ensure_unique_ids,
)


class RemoteAssetSource(StrictModel):
    type: Literal["remote"]
    uri: Annotated[str, Field(min_length=1)]

    @field_validator("uri")
    @classmethod
    def immutable_uri(cls, uri: str) -> str:
        parsed = urlsplit(uri)
        if parsed.scheme not in {"https", "s3", "gs"}:
            raise ValueError("remote asset URI must use https, s3, or gs")
        if not parsed.netloc:
            raise ValueError("remote asset URI must include an authority/bucket")
        return uri


def _validate_relative_path(path: str) -> str:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or path.startswith("~") or ".." in pure.parts:
        raise ValueError("asset path must be relative and cannot contain '..'")
    return path


class EnvironmentAssetSource(StrictModel):
    type: Literal["environment"]
    root_variable: EnvironmentVariable
    relative_path: Annotated[str, Field(min_length=1)]

    _relative = field_validator("relative_path")(_validate_relative_path)


class RepositoryAssetSource(StrictModel):
    type: Literal["repository"]
    path: Annotated[str, Field(min_length=1)]

    _relative = field_validator("path")(_validate_relative_path)


AssetSource = Annotated[
    RemoteAssetSource | EnvironmentAssetSource | RepositoryAssetSource,
    Field(discriminator="type"),
]


class LockedAsset(StrictModel):
    id: Identifier
    kind: Literal[
        "mesh",
        "case",
        "data",
        "chemistry",
        "profile",
        "reference_data",
        "geometry",
        "table",
        "udf_source",
        "other",
    ]
    source: AssetSource
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
    size_bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None
    description: str | None = None

    @field_validator("sha256")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        return value.lower()


class AssetsLock(VersionedDocument):
    assets: list[LockedAsset]

    @model_validator(mode="after")
    def unique_assets(self) -> AssetsLock:
        ensure_unique_ids(self.assets, "asset")
        return self

    def by_id(self) -> dict[str, LockedAsset]:
        return {asset.id: asset for asset in self.assets}
