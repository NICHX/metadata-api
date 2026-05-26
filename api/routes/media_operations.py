from fastapi import APIRouter, Depends, Body, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import List
import httpx
import json
import asyncio
import os

from api.dependencies import verify_auth
from api.schemas.media import (
    FileInfo,
    PreviewRenameRequest,
    PreviewRenameResponse,
    RenamePreviewResult,
    RenameRequest,
    OrganizeRequest,
    OrganizeResponse,
    OrganizeItem,
    ScrapeRequest,
    TmdbSearchRequest,
    TmdbSearchResponse,
    TmdbCandidate,
    ManualScrapeRequest,
    ManualScrapeItem,
    ManualScrapeResponse,
)
from api.services.recognition_service import RecognitionService, prepopulate_ai_cache
from api.services.media_operations_service import MediaOperationsService, _estimate_ai_cost
from api.services.ai_service import get_and_reset_token_usage
from api.services.hardlink_service import organize_file, DEFAULT_MOVIE_TEMPLATE, DEFAULT_TV_TEMPLATE
from db.tmdb_api import fetch_tmdb_candidates_async

# TMDb 图片 CDN 基础地址
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

router = APIRouter(
    prefix="/api/v1/media",
    tags=["media-operations"],
    dependencies=[Depends(verify_auth)],
)


@router.post("/preview-rename", response_model=PreviewRenameResponse)
async def preview_rename(
    files: List[FileInfo] = Body(
        ...,
        examples=[
            [
                {"path": "/movies/Breaking.Bad.S01E01.Pilot.mkv", "name": "Breaking.Bad.S01E01.Pilot.mkv"}
            ]
        ]
    ),
    tv_template: str = Body(None, description="剧集命名模板"),
    movie_template: str = Body(None, description="电影命名模板"),
):
    """返回重命名预览，不实际操作文件"""
    results = []

    for file_info in files:
        try:
            result = await RecognitionService.recognize_media(
                filename=file_info.name,
                filepath=file_info.path,
            )
            preview_result = RenamePreviewResult(
                original=file_info.name,
                suggested=result.suggested_new_name or file_info.name,
                target_path=None,
                metadata=result.metadata,
            )
            results.append(preview_result)
        except Exception as e:
            results.append(
                RenamePreviewResult(
                    original=file_info.name,
                    suggested=file_info.name,
                    target_path=None,
                    metadata=None,
                )
            )

    return PreviewRenameResponse(results=results)


@router.post("/tmdb-search", response_model=TmdbSearchResponse)
async def tmdb_search(request: TmdbSearchRequest = Body(...)):
    """搜索 TMDb 媒体信息，返回候选列表供用户选择"""
    from api.config import settings
    from db.tmdb_api import fetch_tmdb_candidates_async, fetch_tmdb_by_id_async, fetch_tmdb_collection_by_id_async
    from utils.helpers import extract_year_from_release

    results = []

    # --- 合集 Collection（按 ID 直查）---
    if request.type == "collection" and request.tmdb_id:
        title, cid, msg, meta = await fetch_tmdb_collection_by_id_async(
            str(request.tmdb_id), api_key=settings.tmdb_api_key
        )
        if cid != "None":
            poster = meta.get("poster", "") or ""
            if poster and not poster.startswith("/"):
                poster = "/" + poster if poster else ""
            results.append(TmdbCandidate(
                id=int(cid),
                title=title,
                alt_title=meta.get("original_title", ""),
                year=extract_year_from_release(meta.get("release", "")),
                type="collection",
                media_category="collection",
                poster=poster,
                overview=meta.get("overview", ""),
                rating=meta.get("rating"),
            ))
        return TmdbSearchResponse(results=results, total=len(results))

    # --- 合集 Collection（按名称搜索）---
    if request.type == "collection" and request.title:
        from db.tmdb_api import fetch_tmdb_candidates_raw_async, fetch_tmdb_credits_async
        candidates = await fetch_tmdb_candidates_raw_async(
            title=request.title,
            year=str(request.year) if request.year else None,
            is_tv=False,
            api_key=settings.tmdb_api_key,
        )
        for c in candidates:
            results.append(TmdbCandidate(
                id=c.get("id", 0),
                title=c.get("title", ""),
                alt_title=c.get("alt_title", ""),
                year=extract_year_from_release(c.get("release")) if c.get("release") else None,
                type="collection",
                media_category="collection",
                poster=c.get("poster", ""),
                overview=c.get("overview", ""),
                rating=c.get("rating"),
            ))
        return TmdbSearchResponse(results=results, total=len(results))

    # --- 季 Season（需要先找到剧集 ID，再获取季列表）---
    if request.type == "season":
        from db.tmdb_api import fetch_tmdb_candidates_raw_async, fetch_tmdb_season_data_async
        tv_candidates = await fetch_tmdb_candidates_raw_async(
            title=request.title,
            year=str(request.year) if request.year else None,
            is_tv=True,
            api_key=settings.tmdb_api_key,
        )
        for tv_c in tv_candidates[:5]:
            tv_id = tv_c.get("id")
            season_num = request.season_number
            if season_num:
                season_data = await fetch_tmdb_season_data_async(
                    str(tv_id), season_num, settings.tmdb_api_key
                )
                if season_data:
                    season_poster = season_data.get("poster_path", "") or ""
                    ep_count = len(season_data.get("episodes") or [])
                    season_name = season_data.get("name", "") or f"第 {season_num} 季"
                    overview = season_data.get("overview", "") or tv_c.get("overview", "")
                    title_text = f"{tv_c.get('title', '')} - {season_name}"
                    results.append(TmdbCandidate(
                        id=int(tv_id) * 1000 + season_num,
                        title=title_text,
                        alt_title=tv_c.get("alt_title", ""),
                        year=extract_year_from_release(season_data.get("air_date", "")),
                        type="season",
                        media_category="season",
                        season_number=season_num,
                        poster=season_poster,
                        overview=overview,
                        rating=tv_c.get("rating"),
                    ))
            else:
                tv_info, cid, msg, tv_meta = await fetch_tmdb_by_id_async(
                    str(tv_id), is_tv=True, api_key=settings.tmdb_api_key
                )
                seasons = tv_meta.get("seasons") or []
                for s in seasons:
                    if s.get("season_number", 0) == 0:
                        continue
                    s_num = s.get("season_number", 1)
                    s_poster = s.get("poster_path", "") or ""
                    s_name = s.get("name", "") or f"第 {s_num} 季"
                    s_ep_count = s.get("episode_count", 0)
                    s_overview = s.get("overview", "")
                    title_text = f"{tv_info} - {s_name} ({s_ep_count}集)"
                    results.append(TmdbCandidate(
                        id=int(tv_id) * 1000 + s_num,
                        title=title_text,
                        alt_title=tv_c.get("alt_title", ""),
                        year=extract_year_from_release(s.get("air_date", "")),
                        type="season",
                        media_category="season",
                        season_number=s_num,
                        poster=s_poster,
                        overview=s_overview or tv_c.get("overview", ""),
                        rating=tv_c.get("rating"),
                    ))
        return TmdbSearchResponse(results=results, total=len(results))

    # --- 细化分类: documentary / music_video / variety / short ---
    is_special_category = request.type in ("documentary", "music_video", "variety", "short")
    if is_special_category:
        category_type = request.type
        candidates = []
        for search_is_tv in [True, False]:
            candidates.extend(await fetch_tmdb_candidates_async(
                title=request.title,
                year=str(request.year) if request.year else None,
                is_tv=search_is_tv,
                api_key=settings.tmdb_api_key,
            ))
        for c in candidates:
            results.append(TmdbCandidate(
                id=c.get("id", 0),
                title=c.get("title", ""),
                alt_title=c.get("alt_title", ""),
                year=extract_year_from_release(c.get("release")) if c.get("release") else None,
                type="tv" if c.get("is_tv") else "movie",
                media_category=category_type,
                poster=c.get("poster", ""),
                overview=c.get("overview", ""),
                rating=c.get("rating"),
            ))
        return TmdbSearchResponse(results=results, total=len(results))

    # --- 原始逻辑: movie / tv / auto（保持兼容）---
    if request.tmdb_id:
        for is_tv in ([True, False] if request.type == "auto" else [request.type == "tv"]):
            title, cid, msg, meta = await fetch_tmdb_by_id_async(
                str(request.tmdb_id), is_tv=is_tv, api_key=settings.tmdb_api_key
            )
            if cid != "None":
                poster = meta.get("poster", "") or ""
                if poster and not poster.startswith("/"):
                    poster = "/" + poster if poster else ""
                results.append(TmdbCandidate(
                    id=int(cid),
                    title=title,
                    alt_title=meta.get("original_title", ""),
                    year=extract_year_from_release(meta.get("release", "")),
                    type="tv" if is_tv else "movie",
                    poster=poster,
                    overview=meta.get("overview", ""),
                    rating=meta.get("rating"),
                ))
                break

    if not results:
        candidates = []
        if request.type == "auto":
            for search_is_tv in [True, False]:
                candidates.extend(await fetch_tmdb_candidates_async(
                    title=request.title,
                    year=str(request.year) if request.year else None,
                    is_tv=search_is_tv,
                    api_key=settings.tmdb_api_key,
                ))
        else:
            is_tv = request.type == "tv"
            candidates = await fetch_tmdb_candidates_async(
                title=request.title,
                year=str(request.year) if request.year else None,
                is_tv=is_tv,
                api_key=settings.tmdb_api_key,
            )

        for c in candidates:
            results.append(TmdbCandidate(
                id=c.get("id", 0),
                title=c.get("title", ""),
                alt_title=c.get("alt_title", ""),
                year=extract_year_from_release(c.get("release")) if c.get("release") else None,
                type="tv" if c.get("is_tv") else "movie",
                poster=c.get("poster", ""),
                overview=c.get("overview", ""),
                rating=c.get("rating"),
            ))

    return TmdbSearchResponse(results=results, total=len(results))


@router.post("/manual-scrape", response_model=ManualScrapeResponse)
async def manual_scrape(request: ManualScrapeRequest = Body(...)):
    """手动刮削 — 使用用户指定 TMDb ID 或搜索结果刮削（绕过自动识别）"""
    if not request.files:
        return ManualScrapeResponse(total=0, success=0, failed=0, results=[])

    from api.schemas.media import EpisodeMetadata
    from api.services.media_operations_service import MediaOperationsService
    from db.tmdb_api import fetch_tmdb_candidates_raw_async, fetch_tmdb_credits_async, fetch_tmdb_episode_meta_async
    from utils.helpers import candidate_to_result, extract_year_from_release, async_save_image
    from api.config import settings
    import re

    media_category = request.media_category
    collection_id = request.collection_id
    season_number = request.season_number
    tv_id = request.tv_id

    async def _process_one_file(file_info):
        item = ManualScrapeItem(
            original_path=file_info.path,
            original_name=file_info.name,
            success=False,
            status="未开始",
        )

        if not os.path.exists(file_info.path):
            item.status = "源文件不存在"
            item.errors.append("源文件不存在")
            return item

        try:
            if media_category == "collection":
                from db.tmdb_api import fetch_tmdb_collection_by_id_async
                cid_to_use = collection_id or request.tmdb_id
                if not cid_to_use:
                    item.status = "缺少合集ID"
                    item.errors.append("合集刮削需要提供合集ID")
                    return item
                coll_title, cid, coll_msg, coll_meta = await fetch_tmdb_collection_by_id_async(
                    str(cid_to_use), api_key=settings.tmdb_api_key
                )
                if cid == "None":
                    item.status = "合集ID无效"
                    item.errors.append("TMDb 未找到该合集")
                    return item
                candidates = [{
                    "title": coll_title, "alt_title": "", "id": cid,
                    "release": coll_meta.get("release", ""),
                    "poster": coll_meta.get("poster", ""),
                    "rating": coll_meta.get("rating", 0),
                    "overview": coll_meta.get("overview", ""),
                    "meta": coll_meta, "is_tv": False,
                }]

            elif media_category == "season":
                from db.tmdb_api import fetch_tmdb_season_data_async, fetch_tmdb_by_id_async
                tv_id_to_use = tv_id or request.tmdb_id
                season_num_to_use = season_number or 1
                if not tv_id_to_use:
                    item.status = "缺少剧集ID"
                    item.errors.append("季刮削需要提供剧集ID(tv_id)")
                    return item
                tv_title, tv_cid, tv_msg, tv_meta = await fetch_tmdb_by_id_async(
                    str(tv_id_to_use), is_tv=True, api_key=settings.tmdb_api_key
                )
                if tv_cid == "None":
                    item.status = "剧集ID无效"
                    item.errors.append("TMDb 未找到该剧集")
                    return item
                season_data = await fetch_tmdb_season_data_async(
                    str(tv_id_to_use), season_num_to_use, settings.tmdb_api_key
                )
                if not season_data:
                    item.status = "季数据获取失败"
                    item.errors.append("TMDb 未找到该季信息")
                    return item
                season_name = season_data.get("name", "") or f"第 {season_num_to_use} 季"
                candidate_meta = {
                    "overview": season_data.get("overview", "") or tv_meta.get("overview", ""),
                    "rating": tv_meta.get("rating", 0),
                    "poster": season_data.get("poster_path", "") or tv_meta.get("poster", ""),
                    "fanart": tv_meta.get("fanart", ""),
                    "release": season_data.get("air_date", "") or tv_meta.get("release", ""),
                    "original_title": tv_meta.get("original_title", ""),
                    "genres": tv_meta.get("genres", []),
                    "studios": tv_meta.get("studios", []),
                    "runtime": tv_meta.get("runtime"),
                    "status": season_data.get("status", "") or tv_meta.get("status", ""),
                    "seasons": tv_meta.get("seasons", []),
                }
                candidates = [{
                    "title": f"{tv_title} - {season_name}",
                    "alt_title": tv_meta.get("original_title", ""),
                    "id": tv_cid, "release": candidate_meta["release"],
                    "poster": candidate_meta["poster"],
                    "rating": candidate_meta["rating"],
                    "overview": candidate_meta["overview"],
                    "meta": candidate_meta, "is_tv": True,
                }]

            else:
                if request.tmdb_id:
                    from db.tmdb_api import fetch_tmdb_by_id_raw_async
                    is_tv = request.media_type == "tv"
                    id_title, cid, id_msg, id_meta = await fetch_tmdb_by_id_raw_async(
                        str(request.tmdb_id), is_tv=is_tv, api_key=settings.tmdb_api_key
                    )
                    if cid != "None":
                        candidates = [{
                            "title": id_title, "alt_title": id_meta.get("original_title", ""),
                            "id": cid, "release": id_meta.get("release", ""),
                            "poster": id_meta.get("poster", ""),
                            "rating": id_meta.get("rating", 0),
                            "overview": id_meta.get("overview", ""),
                            "meta": id_meta, "is_tv": is_tv,
                        }]
                    else:
                        candidates = []
                else:
                    candidates_raw = await fetch_tmdb_candidates_raw_async(
                        title=str(request.title or ""),
                        year=request.year,
                        is_tv=None if request.media_type == "auto" else (request.media_type == "tv"),
                        api_key=settings.tmdb_api_key,
                    )
                    candidates = [c for c in candidates_raw if c.get("id") == request.tmdb_id] if request.tmdb_id else candidates_raw

            if not candidates:
                item.status = "TMDb 未匹配到结果"
                item.errors.append("未找到匹配的 TMDb 条目")
                return item

            candidate = candidates[0]
            match_tuple = candidate_to_result(candidate, "手动匹配")
            if match_tuple and len(match_tuple) >= 4:
                _, mid, _, metadata_dict = match_tuple
            else:
                item.status = "TMDb 数据解析失败"
                item.errors.append("数据解析失败")
                return item

            metadata = EpisodeMetadata(
                title=candidate.get("title", request.title or "Unknown"),
                original_title=candidate.get("alt_title", ""),
                year=extract_year_from_release(candidate.get("release")) or str(request.year or ""),
                season=getattr(candidate, "season", None),
                episode=getattr(candidate, "episode", None),
                poster=candidate.get("poster", ""),
                fanart=metadata_dict.get("backdrop_path", ""),
                genres=metadata_dict.get("genres", []),
                rating=candidate.get("rating"),
                overview=metadata_dict.get("overview", ""),
            )

            if media_category:
                metadata.media_category = media_category

            if media_category == "collection":
                metadata.collection_id = int(candidate.get("id", 0)) if candidate.get("id") else None
                metadata.collection_name = candidate.get("title", "")
                metadata.collection_poster = candidate.get("poster", "")

            if media_category == "season":
                metadata.season_number = season_number or 1
                metadata.tv_id = int(candidate.get("id", 0)) if candidate.get("id") else None
                metadata.s_poster = metadata_dict.get("poster", "") or metadata.poster

            try:
                is_tv_type = candidate.get("is_tv", False) or request.media_type == "tv"
                t_id = str(candidate.get("id", ""))
                if t_id and t_id != "None":
                    actors, directors = await fetch_tmdb_credits_async(
                        t_id, is_tv=is_tv_type, api_key=settings.tmdb_api_key
                    )
                    metadata.actors = actors
                    metadata.directors = directors
            except Exception:
                pass

            # 解析文件名获取季/集信息（仅 TV 剧集），获取剧照
            if not media_category and (candidate.get("is_tv") or request.media_type == "tv"):
                try:
                    parse_result = await asyncio.to_thread(RecognitionService.parse_filename, file_info.name)
                    ep_season = parse_result.season
                    ep_episode = parse_result.episode
                    if ep_season and ep_episode:
                        metadata.season = ep_season
                        metadata.episode = ep_episode
                        ep_title, ep_plot, still = await fetch_tmdb_episode_meta_async(
                            str(candidate.get("id", "")),
                            ep_season, ep_episode,
                            settings.tmdb_api_key,
                            candidate.get("title", ""),
                            settings.bgm_api_key,
                        )
                        metadata.ep_title = ep_title
                        metadata.ep_plot = ep_plot
                        metadata.still = still
                except Exception:
                    pass

            sidecar_result = await MediaOperationsService._write_sidecar_files(
                file_info.path,
                metadata,
                download_images=request.download_images,
                write_nfo_flag=request.write_nfo,
                overwrite=True,
            )

            item.nfo_written = sidecar_result.get("nfo_written", [])
            item.images_downloaded = sidecar_result.get("images_downloaded", [])
            item.errors = sidecar_result.get("errors", [])
            item.success = len(item.errors) == 0
            item.status = "刮削完成" if item.success else "部分完成"
            item.recognized_title = metadata.title
            item.actors_count = len(metadata.actors)
            item.directors = metadata.directors

            if request.download_actor_images and metadata.actors:
                try:
                    actor_dir = os.path.join(os.path.dirname(file_info.path), ".actor")
                    os.makedirs(actor_dir, exist_ok=True)
                    dl_tasks = []
                    for actor in metadata.actors:
                        name = actor.get("name", "").strip()
                        thumb = actor.get("thumb", "").strip()
                        if name and thumb:
                            safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
                            actor_path = os.path.join(actor_dir, f"{safe_name}.jpg")
                            if not os.path.exists(actor_path):
                                dl_tasks.append(async_save_image(actor_path, thumb))
                    if dl_tasks:
                        await asyncio.gather(*dl_tasks)
                        item.images_downloaded.append(
                            f"演员头像: {len(dl_tasks)}个 -> {actor_dir}"
                        )
                except Exception:
                    pass

        except Exception as e:
            item.status = f"刮削失败: {str(e)}"
            item.errors.append(str(e))

        return item

    tasks = [_process_one_file(f) for f in request.files]
    results = list(await asyncio.gather(*tasks))

    total = len(results)
    success_count = sum(1 for r in results if r.success)
    failed_count = sum(1 for r in results if not r.success)

    return ManualScrapeResponse(
        total=total,
        success=success_count,
        failed=failed_count,
        results=results,
    )


@router.post("/manual-scrape/stream")
async def manual_scrape_stream(request: ManualScrapeRequest = Body(...)):
    """手动刮削流式接口 — 逐文件返回进度，实时更新进度条"""
    if not request.files:
        return StreamingResponse(
            iter([json.dumps({"type": "error", "message": "没有指定要刮削的文件"}) + "\n"]),
            media_type="application/x-ndjson"
        )

    async def generate_manual_results():
        total = len(request.files)
        yield json.dumps({"type": "progress", "message": f"开始手动刮削 {total} 个文件..."}) + "\n"
        _started = 0
        _tmdb_cache_by_id = {}
        _tmdb_cache_credits = {}
        _tmdb_cache_season = {}
        _tmdb_cache_collection = {}

        from api.schemas.media import EpisodeMetadata
        from api.services.media_operations_service import MediaOperationsService
        from db.tmdb_api import fetch_tmdb_candidates_raw_async, fetch_tmdb_credits_async, fetch_tmdb_episode_meta_async
        from utils.helpers import candidate_to_result, extract_year_from_release, async_save_image
        from api.config import settings
        from utils.log_buffer import push_log
        import re

        media_category = request.media_category
        collection_id = request.collection_id
        season_number = request.season_number
        tv_id = request.tv_id

        async def _process_one(idx, file_info):
            nonlocal _started
            _started += 1
            await push_log(f"[{idx}/{total}] 开始处理: {file_info.name}")
            item = ManualScrapeItem(
                original_path=file_info.path,
                original_name=file_info.name,
                success=False,
                status="未开始",
            )

            if not os.path.exists(file_info.path):
                item.status = "源文件不存在"
                item.errors.append("源文件不存在")
                return idx, item

            try:
                if media_category == "collection":
                    from db.tmdb_api import fetch_tmdb_collection_by_id_async
                    cid_to_use = collection_id or request.tmdb_id
                    if not cid_to_use:
                        item.status = "缺少合集ID"
                        item.errors.append("合集刮削需要提供合集ID")
                        return idx, item
                    _cache_key_coll = f"coll:{cid_to_use}"
                    if _cache_key_coll not in _tmdb_cache_collection:
                        _tmdb_cache_collection[_cache_key_coll] = await fetch_tmdb_collection_by_id_async(
                            str(cid_to_use), api_key=settings.tmdb_api_key
                        )
                    coll_title, cid, coll_msg, coll_meta = _tmdb_cache_collection[_cache_key_coll]
                    if cid == "None":
                        item.status = "合集ID无效"
                        item.errors.append("TMDb 未找到该合集")
                        return idx, item
                    candidates = [{
                        "title": coll_title, "alt_title": "", "id": cid,
                        "release": coll_meta.get("release", ""),
                        "poster": coll_meta.get("poster", ""),
                        "rating": coll_meta.get("rating", 0),
                        "overview": coll_meta.get("overview", ""),
                        "meta": coll_meta, "is_tv": False,
                    }]

                elif media_category == "season":
                    from db.tmdb_api import fetch_tmdb_season_data_async, fetch_tmdb_by_id_async
                    tv_id_to_use = tv_id or request.tmdb_id
                    season_num_to_use = season_number or 1
                    if not tv_id_to_use:
                        item.status = "缺少剧集ID"
                        item.errors.append("季刮削需要提供剧集ID(tv_id)")
                        return idx, item
                    tv_title, tv_cid, tv_msg, tv_meta = await fetch_tmdb_by_id_async(
                        str(tv_id_to_use), is_tv=True, api_key=settings.tmdb_api_key
                    )
                    if tv_cid == "None":
                        item.status = "剧集ID无效"
                        item.errors.append("TMDb 未找到该剧集")
                        return idx, item
                    _cache_key_season = f"season:{tv_id_to_use}:{season_num_to_use}"
                    if _cache_key_season not in _tmdb_cache_season:
                        _tmdb_cache_season[_cache_key_season] = await fetch_tmdb_season_data_async(
                            str(tv_id_to_use), season_num_to_use, settings.tmdb_api_key
                        )
                    season_data = _tmdb_cache_season[_cache_key_season]
                    if not season_data:
                        item.status = "季数据获取失败"
                        item.errors.append("TMDb 未找到该季信息")
                        return idx, item
                    season_name = season_data.get("name", "") or f"第 {season_num_to_use} 季"
                    candidate_meta = {
                        "overview": season_data.get("overview", "") or tv_meta.get("overview", ""),
                        "rating": tv_meta.get("rating", 0),
                        "poster": season_data.get("poster_path", "") or tv_meta.get("poster", ""),
                        "fanart": tv_meta.get("fanart", ""),
                        "release": season_data.get("air_date", "") or tv_meta.get("release", ""),
                        "original_title": tv_meta.get("original_title", ""),
                        "genres": tv_meta.get("genres", []),
                        "studios": tv_meta.get("studios", []),
                        "runtime": tv_meta.get("runtime"),
                        "status": season_data.get("status", "") or tv_meta.get("status", ""),
                        "seasons": tv_meta.get("seasons", []),
                    }
                    candidates = [{
                        "title": f"{tv_title} - {season_name}",
                        "alt_title": tv_meta.get("original_title", ""),
                        "id": tv_cid, "release": candidate_meta["release"],
                        "poster": candidate_meta["poster"],
                        "rating": candidate_meta["rating"],
                        "overview": candidate_meta["overview"],
                        "meta": candidate_meta, "is_tv": True,
                    }]

                else:
                    if request.tmdb_id:
                        from db.tmdb_api import fetch_tmdb_by_id_raw_async
                        is_tv = request.media_type == "tv"
                        _cache_key_id = f"by_id:{request.tmdb_id}:{is_tv}"
                        if _cache_key_id not in _tmdb_cache_by_id:
                            _tmdb_cache_by_id[_cache_key_id] = await fetch_tmdb_by_id_raw_async(
                                str(request.tmdb_id), is_tv=is_tv, api_key=settings.tmdb_api_key
                            )
                        id_title, cid, id_msg, id_meta = _tmdb_cache_by_id[_cache_key_id]
                        if cid != "None":
                            candidates = [{
                                "title": id_title, "alt_title": id_meta.get("original_title", ""),
                                "id": cid, "release": id_meta.get("release", ""),
                                "poster": id_meta.get("poster", ""),
                                "rating": id_meta.get("rating", 0),
                                "overview": id_meta.get("overview", ""),
                                "meta": id_meta, "is_tv": is_tv,
                            }]
                        else:
                            candidates = []
                    else:
                        candidates_raw = await fetch_tmdb_candidates_raw_async(
                            title=str(request.title or ""),
                            year=request.year,
                            is_tv=None if request.media_type == "auto" else (request.media_type == "tv"),
                            api_key=settings.tmdb_api_key,
                        )
                        candidates = [c for c in candidates_raw if c.get("id") == request.tmdb_id] if request.tmdb_id else candidates_raw

                if not candidates:
                    item.status = "TMDb 未匹配到结果"
                    item.errors.append("未找到匹配的 TMDb 条目")
                    return idx, item

                candidate = candidates[0]
                match_tuple = candidate_to_result(candidate, "手动匹配")
                if match_tuple and len(match_tuple) >= 4:
                    _, mid, _, metadata_dict = match_tuple
                else:
                    item.status = "TMDb 数据解析失败"
                    item.errors.append("数据解析失败")
                    return idx, item

                metadata = EpisodeMetadata(
                    title=candidate.get("title", request.title or "Unknown"),
                    original_title=candidate.get("alt_title", ""),
                    year=extract_year_from_release(candidate.get("release")) or str(request.year or ""),
                    season=getattr(candidate, "season", None),
                    episode=getattr(candidate, "episode", None),
                    poster=candidate.get("poster", ""),
                    fanart=metadata_dict.get("backdrop_path", ""),
                    genres=metadata_dict.get("genres", []),
                    rating=candidate.get("rating"),
                    overview=metadata_dict.get("overview", ""),
                )

                if media_category:
                    metadata.media_category = media_category

                if media_category == "collection":
                    metadata.collection_id = int(candidate.get("id", 0)) if candidate.get("id") else None
                    metadata.collection_name = candidate.get("title", "")
                    metadata.collection_poster = candidate.get("poster", "")

                if media_category == "season":
                    metadata.season_number = season_number or 1
                    metadata.tv_id = int(candidate.get("id", 0)) if candidate.get("id") else None
                    metadata.s_poster = metadata_dict.get("poster", "") or metadata.poster

                try:
                    is_tv_type = candidate.get("is_tv", False) or request.media_type == "tv"
                    t_id = str(candidate.get("id", ""))
                    if t_id and t_id != "None":
                        _cache_key_cred = f"cred:{t_id}:{is_tv_type}"
                        if _cache_key_cred not in _tmdb_cache_credits:
                            _tmdb_cache_credits[_cache_key_cred] = await fetch_tmdb_credits_async(
                                t_id, is_tv=is_tv_type, api_key=settings.tmdb_api_key
                            )
                        actors, directors = _tmdb_cache_credits[_cache_key_cred]
                        metadata.actors = actors
                        metadata.directors = directors
                except Exception:
                    pass

                if not media_category and (candidate.get("is_tv") or request.media_type == "tv"):
                    try:
                        parse_result = await asyncio.to_thread(RecognitionService.parse_filename, file_info.name)
                        ep_season = parse_result.season
                        ep_episode = parse_result.episode
                        if ep_season and ep_episode:
                            metadata.season = ep_season
                            metadata.episode = ep_episode
                            ep_title, ep_plot, still = await asyncio.wait_for(
                                fetch_tmdb_episode_meta_async(
                                    str(candidate.get("id", "")),
                                    ep_season, ep_episode,
                                    settings.tmdb_api_key,
                                    candidate.get("title", ""),
                                    settings.bgm_api_key,
                                ),
                                timeout=10.0
                            )
                            metadata.ep_title = ep_title
                            metadata.ep_plot = ep_plot
                            metadata.still = still
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass

                sidecar_result = await MediaOperationsService._write_sidecar_files(
                    file_info.path, metadata,
                    download_images=request.download_images,
                    write_nfo_flag=request.write_nfo,
                    overwrite=True,
                )

                item.nfo_written = sidecar_result.get("nfo_written", [])
                item.images_downloaded = sidecar_result.get("images_downloaded", [])
                item.errors = sidecar_result.get("errors", [])
                item.success = len(item.errors) == 0
                item.status = "刮削完成" if item.success else "部分完成"
                item.recognized_title = metadata.title
                item.actors_count = len(metadata.actors)
                item.directors = metadata.directors

                if request.download_actor_images and metadata.actors:
                    try:
                        actor_dir = os.path.join(os.path.dirname(file_info.path), ".actor")
                        os.makedirs(actor_dir, exist_ok=True)
                        dl_tasks = []
                        for actor in metadata.actors:
                            name = actor.get("name", "").strip()
                            thumb = actor.get("thumb", "").strip()
                            if name and thumb:
                                safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
                                actor_path = os.path.join(actor_dir, f"{safe_name}.jpg")
                                if not os.path.exists(actor_path):
                                    dl_tasks.append(async_save_image(actor_path, thumb))
                        if dl_tasks:
                            await asyncio.gather(*dl_tasks)
                            item.images_downloaded.append(
                                f"演员头像: {len(dl_tasks)}个 -> {actor_dir}"
                            )
                    except Exception:
                        pass

            except Exception as e:
                item.status = f"刮削失败: {str(e)}"
                item.errors.append(str(e))

            return idx, item

        tasks = [_process_one(idx, file_info) for idx, file_info in enumerate(request.files, 1)]
        completed = 0
        pending = {asyncio.create_task(t) for t in tasks}
        while pending:
            done, pending = await asyncio.wait(pending, timeout=2.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                yield json.dumps({"type": "progress", "message": f"正在获取数据... 已启动 {_started}/{total} 个"}) + "\n"
                continue
            for coro in done:
                try:
                    idx, item = await asyncio.wait_for(coro, timeout=120.0)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue
                completed += 1
                status_icon = "✅" if item.success else "❌"
                await push_log(f"[{idx}/{total}] {status_icon} {item.original_name}: {item.status}")
                yield json.dumps({
                    "type": "result",
                    "index": idx,
                    "total": total,
                    "success": item.success,
                    "data": {
                        "success": item.success,
                        "original_path": item.original_path,
                        "original_name": item.original_name,
                        "recognized_title": item.recognized_title,
                        "status": item.status,
                        "nfo_written": item.nfo_written,
                        "images_downloaded": item.images_downloaded,
                        "errors": item.errors,
                        "actors_count": item.actors_count,
                        "directors": item.directors,
                    }
                }) + "\n"

        await push_log(f"✅ 手动刮削完成: {total} 个文件")
        yield json.dumps({
            "type": "complete",
            "total": total,
        }) + "\n"

    return StreamingResponse(
        generate_manual_results(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/scrape")
async def scrape_metadata(
    request: ScrapeRequest = Body(...),
):
    """刮削 NFO 和图片（仅本地模式可用）"""
    if not request.files:
        return {
            "success": False,
            "message": "没有指定要刮削的文件"
        }
    
    result = await MediaOperationsService.batch_scrape(
        files=request.files,
        source=request.source,
        download_images=request.download_images,
        write_nfo_flag=request.write_nfo
    )

    response_data = {
        "success": result.get("failed", 0) == 0,
        "total": result.get("total", 0),
        "success_count": result.get("success", 0),
        "failed_count": result.get("failed", 0),
        "results": result.get("results", [])
    }
    if result.get("token_usage"):
        response_data["token_usage"] = result["token_usage"]

    return response_data


@router.post("/scrape/stream")
async def scrape_metadata_stream(request: ScrapeRequest = Body(...)):
    """流式刮削 - 实时返回每个文件的刮削结果"""
    if not request.files:
        return StreamingResponse(
            iter([json.dumps({"type": "error", "message": "没有指定要刮削的文件"}) + "\n"]),
            media_type="application/x-ndjson"
        )
    
    async def generate_scrape_results():
        total = len(request.files)
        from utils.log_buffer import push_log

        yield json.dumps({"type": "progress", "message": "准备中 — AI 预加载..."}) + "\n"
        await push_log(f"开始批量刮削 {total} 个文件...")
        await prepopulate_ai_cache(request.files)
        yield json.dumps({"type": "progress", "message": f"AI 预加载完成，开始匹配 {total} 个文件..."}) + "\n"
        await push_log(f"AI 预加载完成，开始匹配 {total} 个文件...")

        # Phase 1: 识别匹配阶段（逐文件输出进度）
        recog_results: dict = {}

        async def _recog_one(idx, file_info):
            try:
                recog = await RecognitionService.recognize_media(
                    filename=file_info.name,
                    filepath=file_info.path,
                    source=request.source,
                    group_id=file_info.group_id,
                )
                return idx, recog
            except Exception as e:
                return idx, None

        recog_tasks = [_recog_one(idx, file_info) for idx, file_info in enumerate(request.files, 1)]
        for coro in asyncio.as_completed(recog_tasks):
            idx, recog = await coro
            recog_results[idx] = recog
            file_info = request.files[idx - 1]
            title = recog.recognized_title if recog and recog.success else "❌ 未匹配"
            yield json.dumps({
                "type": "progress",
                "message": f"[{len(recog_results)}/{total}] 匹配: {file_info.name} → {title}"
            }) + "\n"
            await push_log(f"[{len(recog_results)}/{total}] 匹配: {file_info.name} → {title}")

        yield json.dumps({"type": "progress", "message": f"匹配完成，开始刮削 {total} 个文件..."}) + "\n"
        await push_log(f"匹配完成，开始刮削 {total} 个文件...")

        # Phase 2: 刮削阶段（复用识别结果）
        async def _scrape_one(idx, file_info):
            try:
                recog = recog_results.get(idx)
                if not recog or not recog.success or not recog.metadata:
                    return idx, {
                        "success": False,
                        "original_path": file_info.path,
                        "original_name": file_info.name,
                        "recognized_title": recog.recognized_title if recog else "",
                        "status": "识别失败，无法刮削",
                        "errors": [recog.status if recog else "识别失败"],
                    }, None
                result = await MediaOperationsService._write_sidecar_files(
                    file_info.path,
                    recog.metadata,
                    download_images=request.download_images,
                    write_nfo_flag=request.write_nfo
                )
                result["recognized_title"] = recog.recognized_title
                result["match_id"] = recog.match_id
                result["original_path"] = file_info.path
                result["original_name"] = file_info.name
                result["success"] = len(result.get("errors", [])) == 0
                result["status"] = "刮削完成" if result["success"] else "部分完成"
                return idx, result, None
            except Exception as e:
                return idx, None, e

        tasks = [_scrape_one(idx, file_info) for idx, file_info in enumerate(request.files, 1)]
        pending = {asyncio.create_task(t) for t in tasks}
        completed_scrape = 0
        while pending:
            done, pending = await asyncio.wait(pending, timeout=2.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                yield json.dumps({"type": "progress", "message": f"刮削中... 已完成 {completed_scrape}/{total} 个"}) + "\n"
                continue
            for coro in done:
                idx, result, error = await coro
                file_info = request.files[idx - 1]

                if error:
                    yield json.dumps({
                        "type": "result",
                        "index": idx,
                        "total": total,
                        "success": False,
                        "data": {
                            "success": False,
                            "original_path": file_info.path,
                            "original_name": file_info.name,
                            "status": f"刮削失败: {str(error)}",
                            "errors": [str(error)],
                        }
                    }) + "\n"
                    await push_log(f"❌ [{idx}/{total}] {file_info.name}: 刮削失败: {str(error)}")
                else:
                    yield json.dumps({
                        "type": "result",
                        "index": idx,
                        "total": total,
                        "success": result.get("success", False),
                        "data": {
                            "success": result.get("success", False),
                            "original_path": result.get("original_path", ""),
                            "original_name": result.get("original_name", ""),
                            "recognized_title": result.get("recognized_title", ""),
                            "match_id": result.get("match_id", ""),
                            "status": result.get("status", ""),
                            "nfo_written": result.get("nfo_written", []),
                            "images_downloaded": result.get("images_downloaded", []),
                            "errors": result.get("errors", []),
                        }
                    }) + "\n"
                    await push_log(f"✅ [{idx}/{total}] {result.get('recognized_title', '')}: {result.get('status', '刮削完成')}")

                completed_scrape += 1
                await asyncio.sleep(0.01)

        # 发送完成消息
        token_usage_list = get_and_reset_token_usage()
        complete_msg = {"type": "complete", "total": total}
        if token_usage_list:
            total_prompt = sum(u.get("prompt_tokens", 0) for u in token_usage_list)
            total_completion = sum(u.get("completion_tokens", 0) for u in token_usage_list)
            total_tokens = sum(u.get("total_tokens", 0) for u in token_usage_list)
            costs = _estimate_ai_cost(token_usage_list)
            complete_msg["token_usage"] = {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "calls": len(token_usage_list),
                "cost_cache_miss": costs["cache_miss"],
                "cost_cache_hit": costs["cache_hit"],
            }
        yield json.dumps(complete_msg) + "\n"
        await push_log(f"✅ 批量刮削完成: {total} 个文件")
    
    return StreamingResponse(
        generate_scrape_results(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/rename")
async def rename_files(request: RenameRequest = Body(...)):
    """原地重命名文件（仅本地模式可用）"""
    from api.services.hardlink_service import DEFAULT_MOVIE_TEMPLATE, DEFAULT_TV_TEMPLATE

    results = []

    for file_info in request.files:
        item = {
            "original_path": file_info.path,
            "original_name": file_info.name,
            "new_name": None,
            "new_path": None,
            "success": False,
            "error": None,
        }

        if not os.path.exists(file_info.path):
            item["error"] = "源文件不存在"
            results.append(item)
            continue

        try:
            recog_result = await RecognitionService.recognize_media(
                filename=file_info.name,
                filepath=file_info.path,
            )
        except Exception as e:
            item["error"] = f"识别失败: {str(e)}"
            results.append(item)
            continue

        if not recog_result.success or not recog_result.suggested_new_name:
            item["error"] = f"识别失败: {recog_result.status}"
            results.append(item)
            continue

        new_name = recog_result.suggested_new_name
        dir_name = os.path.dirname(file_info.path)
        new_path = os.path.join(dir_name, new_name)

        item["new_name"] = new_name
        item["new_path"] = new_path

        if request.dry_run:
            item["success"] = True
            results.append(item)
            continue

        if os.path.exists(new_path):
            item["error"] = "目标文件已存在"
            results.append(item)
            continue

        try:
            os.rename(file_info.path, new_path)
            item["success"] = True
        except Exception as e:
            item["error"] = str(e)
            results.append(item)

    success_count = sum(1 for r in results if r["success"])
    failed_count = sum(1 for r in results if not r["success"])

    return {
        "success": failed_count == 0,
        "total": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "dry_run": request.dry_run,
        "results": results,
    }


@router.post("/organize", response_model=OrganizeResponse)
async def organize_files(request: OrganizeRequest = Body(...)):
    """归档整理 — 将识别后的媒体文件硬链接/复制/移动到目标媒体库目录（含重命名）"""
    if not request.files:
        return OrganizeResponse(total=0, success=0, failed=0, skipped=0, results=[])

    movie_template = request.movie_template or DEFAULT_MOVIE_TEMPLATE
    tv_template = request.tv_template or DEFAULT_TV_TEMPLATE

    # Phase 1: 解析所有文件名（仅 guessit + 正则，不调用 AI）
    parsed_files = []
    for file_info in request.files:
        parse_result = RecognitionService.parse_filename(file_info.name)
        is_tv = parse_result.season is not None and parse_result.season > 0
        parsed_files.append({
            "file_info": file_info,
            "parse": parse_result,
            "is_tv": is_tv,
            "dir_key": os.path.dirname(file_info.path),
        })

    # Phase 2: 按源目录分组，每目录只调用一次 recognize_media（含 AI + TMDb）
    # 但只缓存公共元数据（标题/年份/类型），不缓存季/集（每文件不同）
    dir_groups = {}
    for pf in parsed_files:
        dir_path = os.path.dirname(pf["file_info"].path)
        dir_groups.setdefault(dir_path, []).append(pf)

    from api.schemas.common import EpisodeMetadata

    recog_cache = {}  # dir_path → {title, year, original_title, type, id, ep_title}
    for dir_path, group in dir_groups.items():
        sample = group[0]["file_info"]
        found = False
        try:
            recog_result = await RecognitionService.recognize_media(
                filename=sample.name,
                filepath=sample.path,
                group_id=dir_path,
            )
            if recog_result.success and recog_result.metadata:
                m = recog_result.metadata
                recog_cache[dir_path] = {
                    "title": m.title,
                    "original_title": m.original_title or "",
                    "year": m.year or group[0]["parse"].year,
                    "type": m.type,
                    "id": m.id,
                    "ep_title": m.ep_title or "",
                }
                found = True
        except Exception:
            pass
        if not found:
            pr = group[0]["parse"]
            recog_cache[dir_path] = {
                "title": pr.title,
                "original_title": "",
                "year": pr.year,
                "type": "episode" if group[0]["is_tv"] else "movie",
                "id": None,
                "ep_title": "",
            }

    # 收集 AI token 用量
    token_usage_list = get_and_reset_token_usage()
    token_usage = None
    if token_usage_list:
        total_prompt = sum(u.get("prompt_tokens", 0) for u in token_usage_list)
        total_completion = sum(u.get("completion_tokens", 0) for u in token_usage_list)
        total_tokens = sum(u.get("total_tokens", 0) for u in token_usage_list)
        costs = _estimate_ai_cost(token_usage_list)
        token_usage = {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "calls": len(token_usage_list),
            "cost_cache_miss": costs["cache_miss"],
            "cost_cache_hit": costs["cache_hit"],
        }

    from api.services.hardlink_service import _build_target_path
    from db.tmdb_api import fetch_tmdb_episode_meta_async

    # Phase 3: 合并公共元数据 + 每文件的季/集 → 构建完整 EpisodeMetadata
    _ep_title_cache = {}  # (dir, season, episode) → ep_title

    async def _build_metadata(pf, cache_entry):
        pr = pf["parse"]
        meta = EpisodeMetadata(
            title=cache_entry["title"],
            original_title=cache_entry.get("original_title", ""),
            year=cache_entry.get("year") or pr.year,
            season=pr.season,
            episode=pr.episode,
            type=cache_entry.get("type", "episode" if pf["is_tv"] else "movie"),
            ep_title="",
        )
        tmdb_id = cache_entry.get("id")
        if tmdb_id and meta.type == "episode" and meta.season and meta.episode:
            ep_key = (pf["dir_key"], meta.season, meta.episode)
            if ep_key in _ep_title_cache:
                meta.ep_title = _ep_title_cache[ep_key]
            else:
                try:
                    ep_meta = await fetch_tmdb_episode_meta_async(
                        tmdb_id, meta.season, meta.episode
                    )
                    if ep_meta and ep_meta.get("name"):
                        _ep_title_cache[ep_key] = ep_meta["name"]
                        meta.ep_title = ep_meta["name"]
                    else:
                        _ep_title_cache[ep_key] = ""
                except Exception:
                    _ep_title_cache[ep_key] = ""
        return meta

    results = []
    for pf in parsed_files:
        file_info = pf["file_info"]
        cache_entry = recog_cache.get(os.path.dirname(file_info.path), {})
        metadata = await _build_metadata(pf, cache_entry)

        item = OrganizeItem(
            src=file_info.path,
            src_name=file_info.name,
            dst="",
            mode=request.mode,
            success=False,
            title=metadata.title,
            season=metadata.season,
            episode=metadata.episode,
            type=metadata.type,
        )

        if not os.path.exists(file_info.path):
            item.error = "源文件不存在"
            results.append(item)
            continue

        ext = os.path.splitext(file_info.name)[1]

        if request.dry_run:
            dst = _build_target_path(metadata, request.target_root, ext,
                                     movie_template, tv_template, original_name=file_info.name)
            item.dst = dst
            item.success = True
            item.mode = "preview"
            results.append(item)
            continue

        result = organize_file(
            src_path=file_info.path,
            src_name=file_info.name,
            metadata=metadata,
            target_root=request.target_root,
            threshold=request.threshold,
            mode=request.mode,
            movie_template=movie_template,
            tv_template=tv_template,
            skip_linked=request.skip_linked,
            fallback_to_copy=request.fallback_to_copy,
        )
        item.dst = result.get("dst", "")
        item.mode = result.get("mode", request.mode)
        item.success = result.get("success", False)
        item.error = result.get("error")
        item.linked_skipped = result.get("linked_skipped", False)
        results.append(item)

    total = len(results)
    success_count = sum(1 for r in results if r.success)
    failed_count = sum(1 for r in results if not r.success)
    skipped_count = sum(1 for r in results if r.mode in ("already_exists", "linked_skipped"))

    return OrganizeResponse(
        total=total,
        success=success_count,
        failed=failed_count,
        skipped=skipped_count,
        results=results,
        token_usage=token_usage,
    )


TMDB_IMAGE_HOST = "image.tmdb.org"

_image_cache: dict[str, tuple[bytes, str]] = {}
_image_cache_lock = asyncio.Lock()


@router.get("/image")
async def get_image(
    path: str = Query(..., description="图片相对路径，如 /o25Tk1FYQi2BLk0OEAvx2h69QvB.jpg"),
    size: str = Query("original", description="图片尺寸: original/w500/w342/w185"),
):
    """代理 TMDb 图片，客户端直接通过此接口获取海报等图片"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少图片路径参数 path")
    cache_key = f"{size}:{path}"
    async with _image_cache_lock:
        if cache_key in _image_cache:
            content, media_type = _image_cache[cache_key]
            return Response(content=content, media_type=media_type)
    if path.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(path)
        if parsed.netloc != TMDB_IMAGE_HOST:
            raise HTTPException(status_code=400, detail="不支持的图片来源，仅允许 TMDB 图片 CDN")
        image_url = path
    else:
        image_url = f"{TMDB_IMAGE_BASE}/{size}{path}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            content = resp.content
            media_type = resp.headers.get("content-type", "image/jpeg")
        async with _image_cache_lock:
            if len(_image_cache) > 200:
                _image_cache.clear()
            _image_cache[cache_key] = (content, media_type)
        return Response(content=content, media_type=media_type)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"获取图片失败: {str(e)}")


@router.get("/image-url")
async def get_image_url(
    path: str = Query(..., description="图片相对路径，如 /o25Tk1FYQi2BLk0OEAvx2h69QvB.jpg"),
    size: str = Query("original", description="图片尺寸: original/w500/w342/w185"),
):
    """返回 TMDb 图片完整 URL，客户端自行加载"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少图片路径参数 path")
    if path.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(path)
        if parsed.netloc != TMDB_IMAGE_HOST:
            raise HTTPException(status_code=400, detail="不支持的图片来源，仅允许 TMDB 图片 CDN")
        full_url = path
    else:
        full_url = f"{TMDB_IMAGE_BASE}/{size}{path}"
    return {"url": full_url, "size": size}
