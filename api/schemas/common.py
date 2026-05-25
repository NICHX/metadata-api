from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


class MediaMetadata(BaseModel):
    id: Optional[str] = None
    provider: Optional[str] = None  # tmdb/bgm
    title: Optional[str] = None
    original_title: Optional[str] = None
    year: Optional[int] = None
    overview: Optional[str] = None
    poster: Optional[str] = None
    fanart: Optional[str] = None
    rating: Optional[float] = None
    votes: Optional[int] = None
    genres: List[str] = []
    studios: List[str] = []
    release: Optional[str] = None
    status: Optional[str] = None
    runtime: Optional[int] = None


class EpisodeMetadata(MediaMetadata):
    season: Optional[int] = None
    episode: Optional[int] = None
    ep_title: Optional[str] = None
    ep_plot: Optional[str] = None
    still: Optional[str] = None
    s_poster: Optional[str] = None
    # 附加字段用于刮削
    type: Optional[str] = None  # episode/movie
    match_id: Optional[str] = None
    # 分类细化字段
    media_category: Optional[str] = None  # episode/movie/season/tvshow/collection/documentary/music_video/variety/short
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    collection_poster: Optional[str] = None
    collection_overview: Optional[str] = None
    tv_id: Optional[int] = None
    season_number: Optional[int] = None
    # 演职人员
    actors: List[Dict[str, str]] = []
    directors: List[str] = []
