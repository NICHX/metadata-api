import os
import re
import asyncio
import logging
from typing import List, Dict, Any, Optional

from utils.helpers import write_nfo, save_image
from api.services.recognition_service import RecognitionService, prepopulate_ai_cache
from api.services.ai_service import get_and_reset_token_usage
from api.schemas.media import FileInfo, EpisodeMetadata
from api.config import settings

logger = logging.getLogger("media_operations_service")

# DeepSeek deepseek-v4-flash 定价（CNY）
# 缓存未命中: 输入 ¥1/百万 tokens, 输出 ¥2/百万 tokens
# 缓存命中:   输入 ¥0.02/百万 tokens, 输出 ¥2/百万 tokens
AI_INPUT_CACHE_MISS_PER_1K = 0.001    # ¥/1K tokens
AI_INPUT_CACHE_HIT_PER_1K = 0.00002   # ¥/1K tokens
AI_OUTPUT_PRICE_PER_1K = 0.002        # ¥/1K tokens


def _estimate_ai_cost(token_usage_list: list) -> dict:
    cache_miss = 0.0
    cache_hit = 0.0
    for u in token_usage_list:
        prompt_tokens = u.get("prompt_tokens", 0)
        completion_tokens = u.get("completion_tokens", 0)
        cache_miss += (prompt_tokens / 1000) * AI_INPUT_CACHE_MISS_PER_1K
        cache_miss += (completion_tokens / 1000) * AI_OUTPUT_PRICE_PER_1K
        cache_hit += (prompt_tokens / 1000) * AI_INPUT_CACHE_HIT_PER_1K
        cache_hit += (completion_tokens / 1000) * AI_OUTPUT_PRICE_PER_1K
    return {
        "cache_miss": round(cache_miss, 6),
        "cache_hit": round(cache_hit, 6),
    }


class MediaOperationsService:
    @staticmethod
    async def scrape_metadata(
        file_info: FileInfo,
        source: str = "siliconflow_tmdb",
        download_images: bool = True,
        write_nfo_flag: bool = True
    ) -> Dict[str, Any]:
        """刮削单个媒体文件的元数据"""
        logger.info("开始刮削: path=%s, source=%s, download_images=%s, write_nfo=%s",
                     file_info.path, source, download_images, write_nfo_flag)
        result = {
            "success": False,
            "original_path": file_info.path,
            "original_name": file_info.name,
            "status": "未开始",
            "nfo_written": [],
            "images_downloaded": [],
            "errors": []
        }
        
        # 检查文件是否存在
        if not os.path.exists(file_info.path):
            result["status"] = "源文件不存在"
            result["errors"].append("源文件不存在")
            return result
        
        # 先识别文件
        recog_result = await RecognitionService.recognize_media(
            filename=file_info.name,
            filepath=file_info.path,
            source=source,
            group_id=file_info.group_id,
        )
        
        if not recog_result.success or not recog_result.metadata:
            result["status"] = "识别失败，无法刮削"
            result["errors"].append(recog_result.status)
            logger.warning("刮削识别失败: path=%s, reason=%s", file_info.path, recog_result.status)
            return result

        result["recognized_title"] = recog_result.recognized_title
        result["match_id"] = recog_result.match_id
        
        # 执行刮削
        try:
            sidecar_result = MediaOperationsService._write_sidecar_files(
                file_info.path,
                recog_result.metadata,
                download_images=download_images,
                write_nfo_flag=write_nfo_flag
            )
            result["nfo_written"] = sidecar_result.get("nfo_written", [])
            result["images_downloaded"] = sidecar_result.get("images_downloaded", [])
            result["errors"] = sidecar_result.get("errors", [])
            result["success"] = len(result["errors"]) == 0
            result["status"] = "刮削完成" if result["success"] else "部分完成"
        except Exception as e:
            result["status"] = f"刮削失败: {str(e)}"
            result["errors"].append(str(e))

        if result["success"]:
            logger.info("刮削完成: path=%s, nfo=%s, images=%s",
                         file_info.path, len(result["nfo_written"]), len(result["images_downloaded"]))
        else:
            logger.warning("刮削失败: path=%s, errors=%s", file_info.path, result["errors"])
        return result
    
    @staticmethod
    async def batch_scrape(
        files: List[FileInfo],
        source: str = "siliconflow_tmdb",
        download_images: bool = True,
        write_nfo_flag: bool = True
    ) -> Dict[str, Any]:
        """批量刮削媒体文件的元数据"""
        logger.info("批量刮削开始: 文件数=%s, source=%s", len(files), source)

        await prepopulate_ai_cache(files)

        async def scrape_single(file_info: FileInfo):
            try:
                result = await MediaOperationsService.scrape_metadata(
                    file_info=file_info,
                    source=source,
                    download_images=download_images,
                    write_nfo_flag=write_nfo_flag
                )
                return result
            except Exception as e:
                return {
                    "success": False,
                    "original_path": file_info.path,
                    "original_name": file_info.name,
                    "status": f"刮削失败: {str(e)}",
                    "errors": [str(e)]
                }
        
        tasks = [scrape_single(file_info) for file_info in files]
        results_list = await asyncio.gather(*tasks)
        
        results = {
            "total": len(files),
            "success": 0,
            "failed": 0,
            "results": results_list
        }

        token_usage_list = get_and_reset_token_usage()
        if token_usage_list:
            total_prompt = sum(u.get("prompt_tokens", 0) for u in token_usage_list)
            total_completion = sum(u.get("completion_tokens", 0) for u in token_usage_list)
            total_tokens = sum(u.get("total_tokens", 0) for u in token_usage_list)
            costs = _estimate_ai_cost(token_usage_list)
            results["token_usage"] = {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "calls": len(token_usage_list),
                "cost_cache_miss": costs["cache_miss"],
                "cost_cache_hit": costs["cache_hit"],
            }
        
        for result in results_list:
            if result.get("success"):
                results["success"] += 1
            else:
                results["failed"] += 1

        logger.info("批量刮削完成: 总计=%s, 成功=%s, 失败=%s", results["total"], results["success"], results["failed"])
        return results
    
    @staticmethod
    def _write_sidecar_files(
        target_path: str,
        metadata: EpisodeMetadata,
        download_images: bool = True,
        write_nfo_flag: bool = True
    ) -> Dict[str, Any]:
        """写入 NFO 文件并下载图片"""
        result = {
            "nfo_written": [],
            "images_downloaded": [],
            "errors": []
        }
        
        target_dir = os.path.dirname(target_path)
        media_type = "episode" if metadata.season and metadata.episode else "movie"
        is_tv = media_type == "episode"
        
        image_tasks = []
        
        try:
            if is_tv:
                # 剧集处理
                ep_nfo = os.path.splitext(target_path)[0] + ".nfo"
                if write_nfo_flag and not os.path.exists(ep_nfo):
                    nfo_data = MediaOperationsService._metadata_to_nfo_data(metadata, "episode")
                    write_nfo(ep_nfo, nfo_data, "episodedetails")
                    result["nfo_written"].append(ep_nfo)
                
                # 缩略图
                thumb_source = metadata.still or metadata.s_poster or metadata.poster
                if thumb_source and download_images:
                    thumb_path = os.path.splitext(target_path)[0] + "-thumb.jpg"
                    if not os.path.exists(thumb_path):
                        image_tasks.append((thumb_path, thumb_source))
                
                # 季和剧集文件夹处理
                cur_dir = target_dir
                dir_name = os.path.basename(cur_dir)
                is_season_folder = bool(
                    re.match(r"^(Season\s*\d+|S\d+)$", dir_name, re.I)
                )
                
                if is_season_folder and os.path.dirname(cur_dir):
                    root_d = os.path.dirname(cur_dir)
                else:
                    root_d = cur_dir
                
                s_num = metadata.season or 1
                try:
                    s_fmt = f"{int(s_num):02d}"
                except Exception:
                    s_fmt = str(s_num)
                
                # 季 NFO
                s_nfo_root = os.path.join(root_d, f"season{s_fmt}.nfo")
                if write_nfo_flag and not os.path.exists(s_nfo_root):
                    nfo_data = MediaOperationsService._metadata_to_nfo_data(metadata, "season")
                    write_nfo(s_nfo_root, nfo_data, "season")
                    result["nfo_written"].append(s_nfo_root)
                
                if metadata.s_poster and download_images:
                    s_poster_root = os.path.join(root_d, f"season{s_fmt}-poster.jpg")
                    if not os.path.exists(s_poster_root):
                        image_tasks.append((s_poster_root, metadata.s_poster))
                
                # 季文件夹内的文件
                if is_season_folder:
                    season_nfo_local = os.path.join(cur_dir, "season.nfo")
                    if write_nfo_flag and not os.path.exists(season_nfo_local):
                        nfo_data = MediaOperationsService._metadata_to_nfo_data(metadata, "season")
                        write_nfo(season_nfo_local, nfo_data, "season")
                        result["nfo_written"].append(season_nfo_local)
                    
                    folder_jpg_local = os.path.join(cur_dir, "folder.jpg")
                    if metadata.s_poster and download_images and not os.path.exists(folder_jpg_local):
                        image_tasks.append((folder_jpg_local, metadata.s_poster))
                
                # 电视节目 NFO 和海报
                tvshow_nfo = os.path.join(root_d, "tvshow.nfo")
                if write_nfo_flag and (not os.path.exists(tvshow_nfo) or MediaOperationsService._nfo_has_empty_plot(tvshow_nfo)):
                    nfo_data = MediaOperationsService._metadata_to_nfo_data(metadata, "tvshow")
                    write_nfo(tvshow_nfo, nfo_data, "tvshow")
                    result["nfo_written"].append(tvshow_nfo)
                
                if metadata.poster and download_images:
                    poster_path = os.path.join(root_d, "poster.jpg")
                    if not os.path.exists(poster_path):
                        image_tasks.append((poster_path, metadata.poster))
            
            else:
                # 电影处理
                movie_nfo = os.path.splitext(target_path)[0] + ".nfo"
                if write_nfo_flag and not os.path.exists(movie_nfo):
                    nfo_data = MediaOperationsService._metadata_to_nfo_data(metadata, "movie")
                    write_nfo(movie_nfo, nfo_data, "movie")
                    result["nfo_written"].append(movie_nfo)
                
                if metadata.poster and download_images:
                    poster_path = os.path.join(target_dir, "poster.jpg")
                    if not os.path.exists(poster_path):
                        image_tasks.append((poster_path, metadata.poster))
                
                if metadata.fanart and download_images:
                    fanart_path = os.path.join(target_dir, "fanart.jpg")
                    if not os.path.exists(fanart_path):
                        image_tasks.append((fanart_path, metadata.fanart))
            
            # 下载图片
            for img_path, img_url in image_tasks:
                try:
                    save_image(img_path, img_url)
                    result["images_downloaded"].append(img_path)
                except Exception as e:
                    result["errors"].append(f"下载图片失败 {img_path}: {str(e)}")
        
        except Exception as e:
            result["errors"].append(f"刮削失败: {str(e)}")
        
        return result
    
    @staticmethod
    def _metadata_to_nfo_data(metadata: EpisodeMetadata, nfo_type: str) -> Dict[str, Any]:
        """将 API 元数据转换为 NFO 写入所需格式"""
        data = {
            "title": metadata.title,
            "original_title": metadata.original_title,
            "year": metadata.year,
            "overview": metadata.overview,
            "poster": metadata.poster,
            "fanart": metadata.fanart,
            "rating": metadata.rating,
            "votes": metadata.votes,
            "genres": metadata.genres,
            "studios": metadata.studios,
            "release": metadata.release,
            "status": metadata.status,
            "runtime": metadata.runtime,
            "s": metadata.season,
            "e": metadata.episode,
            "ep_title": metadata.ep_title,
            "still": metadata.still,
            "s_poster": metadata.s_poster,
            "id": metadata.match_id if hasattr(metadata, "match_id") else metadata.id,
            "provider": metadata.provider,
        }
        return data
    
    @staticmethod
    def _nfo_has_empty_plot(nfo_path: str) -> bool:
        """检查 NFO 是否有空的 plot"""
        if not os.path.exists(nfo_path):
            return False
        try:
            with open(nfo_path, "r", encoding="utf-8") as f:
                content = f.read()
                return "<plot></plot>" in content or "<plot />" in content
        except Exception:
            return False
