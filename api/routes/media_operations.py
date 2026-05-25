from fastapi import APIRouter, Depends, Body, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import List
import httpx
import json
import asyncio
import os

from api.dependencies import get_local_mode_only
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
    dependencies=[Depends(get_local_mode_only)],
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
    from utils.helpers import candidate_to_result, extract_year_from_release, async_save_image, extract_episode_number
    from api.config import settings
    import re
    from guessit import guessit

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
                    pure_name, _ = os.path.splitext(file_info.name)
                    guess_data = guessit(pure_name)
                    ep_season = guess_data.get("season")
                    ep_episode = extract_episode_number(pure_name, guess_data)
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

        from api.schemas.media import EpisodeMetadata
        from api.services.media_operations_service import MediaOperationsService
        from db.tmdb_api import fetch_tmdb_candidates_raw_async, fetch_tmdb_credits_async, fetch_tmdb_episode_meta_async
        from utils.helpers import candidate_to_result, extract_year_from_release, async_save_image, extract_episode_number
        from api.config import settings
        import re
        from guessit import guessit

        media_category = request.media_category
        collection_id = request.collection_id
        season_number = request.season_number
        tv_id = request.tv_id

        async def _process_one(idx, file_info):
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
                    coll_title, cid, coll_msg, coll_meta = await fetch_tmdb_collection_by_id_async(
                        str(cid_to_use), api_key=settings.tmdb_api_key
                    )
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
                    season_data = await fetch_tmdb_season_data_async(
                        str(tv_id_to_use), season_num_to_use, settings.tmdb_api_key
                    )
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
                        actors, directors = await fetch_tmdb_credits_async(
                            t_id, is_tv=is_tv_type, api_key=settings.tmdb_api_key
                        )
                        metadata.actors = actors
                        metadata.directors = directors
                except Exception:
                    pass

                if not media_category and (candidate.get("is_tv") or request.media_type == "tv"):
                    try:
                        pure_name, _ = os.path.splitext(file_info.name)
                        guess_data = guessit(pure_name)
                        ep_season = guess_data.get("season")
                        ep_episode = extract_episode_number(pure_name, guess_data)
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
        for coro in asyncio.as_completed(tasks):
            try:
                idx, item = await asyncio.wait_for(coro, timeout=120.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
            completed += 1
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

        yield json.dumps({"type": "progress", "message": "准备中 — AI 预加载..."}) + "\n"
        await prepopulate_ai_cache(request.files)
        yield json.dumps({"type": "progress", "message": f"AI 预加载完成，开始刮削 {total} 个文件..."}) + "\n"

        async def _process_one(idx, file_info):
            try:
                result = await MediaOperationsService.scrape_metadata(
                    file_info=file_info,
                    source=request.source,
                    download_images=request.download_images,
                    write_nfo_flag=request.write_nfo
                )
                return idx, result, None
            except Exception as e:
                return idx, None, e

        tasks = [_process_one(idx, file_info) for idx, file_info in enumerate(request.files, 1)]
        for coro in asyncio.as_completed(tasks):
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
    if request.dry_run:
        return {"success": True, "message": "预览模式，未执行任何操作", "dry_run": True}
    
    # TODO: 实现真实的重命名逻辑
    return {"success": True, "message": "重命名功能开发中", "results": []}


@router.post("/organize", response_model=OrganizeResponse)
async def organize_files(request: OrganizeRequest = Body(...)):
    """归档整理 — 将识别后的媒体文件硬链接/复制/移动到目标媒体库目录"""
    if not request.files:
        return OrganizeResponse(total=0, success=0, failed=0, skipped=0, results=[])

    movie_template = request.movie_template or DEFAULT_MOVIE_TEMPLATE
    tv_template = request.tv_template or DEFAULT_TV_TEMPLATE
    results = []

    for file_info in request.files:
        item = OrganizeItem(
            src=file_info.path,
            src_name=file_info.name,
            dst="",
            mode=request.mode,
            success=False,
        )

        if not os.path.exists(file_info.path):
            item.error = "源文件不存在"
            results.append(item)
            continue

        try:
            recog_result = await RecognitionService.recognize_media(
                filename=file_info.name,
                filepath=file_info.path,
            )
        except Exception as e:
            item.error = f"识别失败: {str(e)}"
            results.append(item)
            continue

        if not recog_result.success or not recog_result.metadata:
            item.error = f"识别失败: {recog_result.status}"
            results.append(item)
            continue

        metadata = recog_result.metadata

        if request.dry_run:
            ext = os.path.splitext(file_info.name)[1]
            from api.services.hardlink_service import _build_target_path
            dst = _build_target_path(metadata, request.target_root, ext, movie_template, tv_template)
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
        )
        item.dst = result.get("dst", "")
        item.mode = result.get("mode", request.mode)
        item.success = result.get("success", False)
        item.error = result.get("error")
        results.append(item)

    total = len(results)
    success_count = sum(1 for r in results if r.success)
    failed_count = sum(1 for r in results if not r.success)
    skipped_count = sum(1 for r in results if r.mode == "already_exists")

    return OrganizeResponse(
        total=total,
        success=success_count,
        failed=failed_count,
        skipped=skipped_count,
        results=results,
    )


TMDB_IMAGE_HOST = "image.tmdb.org"


@router.get("/image")
async def get_image(
    path: str = Query(..., description="图片相对路径，如 /o25Tk1FYQi2BLk0OEAvx2h69QvB.jpg"),
    size: str = Query("original", description="图片尺寸: original/w500/w342/w185"),
):
    """代理 TMDb 图片，客户端直接通过此接口获取海报等图片"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少图片路径参数 path")
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
            return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
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
