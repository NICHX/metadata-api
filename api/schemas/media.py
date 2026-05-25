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
    source: str = Field("siliconflow_tmdb", description="数据源: siliconflow_tmdb / siliconflow_bgm")
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
    source: str = Field("siliconflow_tmdb", description="数据源: siliconflow_tmdb / siliconflow_bgm")


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
    target_root: str = Field(..., examples=["/media/movies"])
    dry_run: bool = Field(True, description="预览模式，不实际操作")


class ScrapeRequest(BaseModel):
    files: List[FileInfo]
    download_images: bool = Field(True, description="下载海报和剧照")
    write_nfo: bool = Field(True, description="写入NFO文件")
    source: str = Field("siliconflow_tmdb", description="数据源: siliconflow_tmdb / siliconflow_bgm")


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