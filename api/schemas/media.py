from pydantic import BaseModel, Field
from typing import Optional, List
from api.schemas.common import EpisodeMetadata


class MediaFileParseRequest(BaseModel):
    filename: str = Field(..., examples=["Breaking.Bad.S01E01.Pilot.mkv"])


class MediaFileParseResponse(BaseModel):
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    extension: Optional[str] = None
    pure_name: Optional[str] = None


class MediaRecognitionRequest(BaseModel):
    filename: str = Field(..., examples=["Breaking.Bad.S01E01.Pilot.mkv"])
    filepath: Optional[str] = Field(None, examples=["/path/to/Breaking.Bad.S01E01.Pilot.mkv"])
    source: str = Field("tmdb", description="数据源: tmdb / bgm")
    media_type_override: Optional[str] = Field(None, description="媒体类型: auto / movie / tv")
    group_id: Optional[str] = Field(None, description="剧集分组ID，用于共享AI结果")


class MediaRecognitionResponse(BaseModel):
    success: bool
    original_filename: str
    recognized_title: Optional[str] = None
    match_id: Optional[str] = None
    status: str
    metadata: Optional[EpisodeMetadata] = None
    suggested_new_name: Optional[str] = None
    parse_source: Optional[str] = None


class BatchRecognitionRequest(BaseModel):
    files: List[MediaRecognitionRequest]
    source: str = Field("tmdb", description="数据源: tmdb / bgm")


class BatchRecognitionResponse(BaseModel):
    total: int
    success: int
    failed: int
    results: List[MediaRecognitionResponse]


class FileInfo(BaseModel):
    path: str = Field(..., examples=["/path/to/file.mkv"])
    name: str = Field(..., examples=["Breaking.Bad.S01E01.Pilot.mkv"])
    size: Optional[int] = Field(None, examples=[104857600])
    group_id: Optional[str] = Field(None, description="剧集分组ID，同一文件夹结构的文件共享AI结果")


class RenameRequest(BaseModel):
    files: List[FileInfo]
    dry_run: bool = Field(True, description="预览模式，不实际操作")


class OrganizeRequest(BaseModel):
    files: List[FileInfo]
    target_root: str = Field(..., examples=["/media/library"])
    mode: str = Field("hardlink", description="整理模式: hardlink / copy / move")
    threshold: int = Field(1_000_000, description="小文件阈值(字节)，小于此值的文件直接复制而非硬链接")
    movie_template: Optional[str] = Field(None, description="电影路径模板，默认: {title} ({year})/{title}.{ext}")
    tv_template: Optional[str] = Field(None, description="剧集路径模板，默认: {title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d}.{ext}")
    dry_run: bool = Field(True, description="预览模式，不实际操作")


class OrganizeItem(BaseModel):
    src: str
    src_name: str
    dst: str
    mode: str
    success: bool
    error: Optional[str] = None


class OrganizeResponse(BaseModel):
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: List[OrganizeItem] = []


class TmdbCandidate(BaseModel):
    id: int
    title: str
    alt_title: str = ""
    year: Optional[str] = None
    type: str = "movie"
    poster: Optional[str] = None
    overview: Optional[str] = None
    rating: Optional[float] = None
    media_category: Optional[str] = None  # movie/tv/season/collection/documentary/music_video/variety/short
    season_number: Optional[int] = None  # 仅 type=season 时有效


class TmdbSearchRequest(BaseModel):
    title: str = Field("", description="搜索标题（tmdb_id 为空时必填）")
    year: Optional[int] = Field(None, description="年份（可选）")
    type: str = Field("auto", description="媒体类型: auto / movie / tv / season / collection / documentary / music_video / variety / short")
    tmdb_id: Optional[int] = Field(None, description="TMDb ID（可选，优先于标题搜索）")
    media_category: Optional[str] = Field(None, description="细化分类: season/collection/documentary/music_video/variety/short")
    season_number: Optional[int] = Field(None, description="季号（仅 season 分类时可用）")


class TmdbSearchResponse(BaseModel):
    results: List[TmdbCandidate] = []
    total: int = 0


class ManualScrapeRequest(BaseModel):
    files: List[FileInfo]
    source: str = Field("tmdb", description="数据源: tmdb / bgm")
    tmdb_id: Optional[int] = Field(None, description="手动指定的 TMDb ID")
    bgm_id: Optional[int] = Field(None, description="手动指定的 Bangumi ID")
    title: Optional[str] = Field(None, description="手动指定的标题")
    year: Optional[int] = Field(None, description="手动指定的年份")
    media_type: Optional[str] = Field("auto", description="媒体类型: auto / movie / tv")
    download_images: bool = True
    write_nfo: bool = True
    download_actor_images: bool = False
    media_category: Optional[str] = Field(None, description="细化分类: season/collection/documentary/music_video/variety/short")
    season_number: Optional[int] = Field(None, description="季号（仅 season 分类时可用）")
    collection_id: Optional[int] = Field(None, description="合集ID（仅 collection 分类时可用）")
    tv_id: Optional[int] = Field(None, description="剧集ID（仅 season 分类时可用）")


class ManualScrapeItem(BaseModel):
    original_path: str
    original_name: str
    success: bool
    status: str
    recognized_title: str = ""
    nfo_written: List[str] = []
    images_downloaded: List[str] = []
    errors: List[str] = []
    actors_count: int = 0
    directors: List[str] = []


class ManualScrapeResponse(BaseModel):
    total: int = 0
    success: int = 0
    failed: int = 0
    results: List[ManualScrapeItem] = []


class ScrapeRequest(BaseModel):
    files: List[FileInfo]
    download_images: bool = Field(True, description="下载海报和剧照")
    write_nfo: bool = Field(True, description="写入NFO文件")
    source: str = Field("tmdb", description="数据源: tmdb / bgm")


class RenamePreviewResult(BaseModel):
    original: str
    suggested: str
    target_path: Optional[str] = None
    metadata: Optional[EpisodeMetadata] = None


class PreviewRenameRequest(BaseModel):
    files: List[FileInfo]
    tv_template: Optional[str] = Field(None, description="剧集命名模板")
    movie_template: Optional[str] = Field(None, description="电影命名模板")


class PreviewRenameResponse(BaseModel):
    results: List[RenamePreviewResult]


class FileSystemItem(BaseModel):
    name: str = Field(..., description="文件或目录名称")
    path: str = Field(..., description="完整路径")
    is_dir: bool = Field(..., description="是否是目录")
    size: Optional[int] = Field(None, description="文件大小(字节)")
    extension: Optional[str] = Field(None, description="文件扩展名")


class DirectoryContentsResponse(BaseModel):
    current_path: str = Field(..., description="当前目录路径")
    parent_path: Optional[str] = Field(None, description="上级目录路径")
    items: List[FileSystemItem] = Field(default_factory=list, description="目录内容列表")


class ScanMediaFilesResponse(BaseModel):
    scanned_path: str = Field(..., description="扫描的目录路径")
    media_files: List[FileInfo] = Field(default_factory=list, description="找到的媒体文件列表")
    total_count: int = Field(0, description="媒体文件总数")