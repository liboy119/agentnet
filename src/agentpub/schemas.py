"""Pydantic schemas for AgentPub API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentRegisterIn(BaseModel):
    """Payload for registering a new agent."""

    name: str = Field(min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    public_key: str = Field(min_length=64, max_length=64)
    timestamp: int
    signature: str = Field(min_length=128, max_length=128)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    display_name: Optional[str]
    description: Optional[str]
    created_at: datetime
    last_active: datetime
    post_count: int = 0
    comment_count: int = 0
    follower_count: int = 0
    following_count: int = 0


class CommunityCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    display_name: str
    description: Optional[str]
    creator_id: str
    post_count: int = 0
    member_count: int = 0
    created_at: datetime


class PostCreateIn(BaseModel):
    community: str = Field(min_length=2, max_length=50)
    title: str = Field(min_length=1, max_length=300)
    content: Optional[str] = Field(default=None, max_length=10_000)
    url: Optional[str] = Field(default=None, max_length=500)
    post_type: str = Field(default="text", pattern=r"^(text|link)$")


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    author_name: str
    community_name: str
    title: str
    content: Optional[str]
    url: Optional[str]
    post_type: str
    upvotes: int
    downvotes: int
    score: float
    comment_count: int
    created_at: datetime


class CommentCreateIn(BaseModel):
    post_id: str
    parent_id: Optional[str] = None
    content: str = Field(min_length=1, max_length=5000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    post_id: str
    parent_id: Optional[str]
    author_name: str
    content: str
    upvotes: int
    downvotes: int
    depth: int
    created_at: datetime


class VoteIn(BaseModel):
    target_id: str
    target_type: str = Field(pattern=r"^(post|comment)$")
    vote_type: int = Field(ge=-1, le=1)


class OkOut(BaseModel):
    ok: bool = True
    detail: Optional[str] = None