import re
import json
import requests
from urllib.parse import urlparse, parse_qs
import sys

REQUEST_TIMEOUT = 15
MAX_RETRIES = 2


def get_video_id(short_url, retries=MAX_RETRIES):
    for attempt in range(retries + 1):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            }
            res = requests.get(short_url, headers=headers, allow_redirects=False, timeout=REQUEST_TIMEOUT)
            real_url = res.headers.get("Location", "")
            if not real_url:
                res = requests.get(short_url, headers=headers, allow_redirects=True, timeout=REQUEST_TIMEOUT)
                real_url = res.url
            print(f"[INFO] Real URL: {real_url}", file=sys.stderr)
            parsed_url = urlparse(real_url)
            query_params = parse_qs(parsed_url.query)
            modal_id_list = query_params.get("modal_id")
            if modal_id_list:
                video_id = modal_id_list[0]
            else:
                path_list = parsed_url.path.strip("/").split("/")
                video_id = path_list[-1]
            if not video_id or not re.match(r'^\d+$', video_id):
                print(f"[WARN] Suspicious video_id: {video_id}", file=sys.stderr)
            return video_id, real_url
        except requests.Timeout:
            print(f"[ERROR] get_video_id timeout (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
        except requests.ConnectionError as e:
            print(f"[ERROR] get_video_id connection error: {e} (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] get_video_id failed: {e} (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
    return None, None


def get_video_info(video_id, retries=MAX_RETRIES):
    for attempt in range(retries + 1):
        try:
            url = f"https://m.douyin.com/share/video/{video_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            }
            res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            res.encoding = "utf-8"

            if res.status_code != 200:
                print(f"[WARN] HTTP {res.status_code} for video {video_id} (attempt {attempt + 1})", file=sys.stderr)
                if attempt < retries:
                    continue
                return {"error": f"HTTP {res.status_code}", "video_id": video_id}

            match_list = re.findall(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", res.text)
            if not match_list:
                print("[WARN] _ROUTER_DATA not found, trying RENDER_DATA", file=sys.stderr)
                match_list = re.findall(r"window\._RENDER_DATA\s*=\s*(.*?)</script>", res.text)
                if match_list:
                    import urllib.parse
                    try:
                        render_data = json.loads(urllib.parse.unquote(match_list[0]))
                        print(f"[INFO] RENDER_DATA keys: {list(render_data.keys())}", file=sys.stderr)
                        return {"raw_keys": list(render_data.keys()), "source": "RENDER_DATA", "html_length": len(res.text)}
                    except json.JSONDecodeError:
                        print("[WARN] RENDER_DATA JSON parse failed", file=sys.stderr)

            if not match_list:
                print("[WARN] No data found in page", file=sys.stderr)
                return {"error": "No data found in page", "html_length": len(res.text)}

            data_dict = json.loads(match_list[0])
            print(f"[INFO] _ROUTER_DATA keys: {list(data_dict.keys())}", file=sys.stderr)

            loader_data = data_dict.get("loaderData", {})
            print(f"[INFO] loaderData keys: {list(loader_data.keys())}", file=sys.stderr)

            video_key = None
            for key in loader_data:
                if "video" in key.lower() and "page" in key.lower():
                    video_key = key
                    break
            if not video_key:
                for key in loader_data:
                    if "video" in key.lower():
                        video_key = key
                        break

            if not video_key:
                return {"raw_keys": list(loader_data.keys()), "source": "ROUTER_DATA", "html_length": len(res.text)}

            page_data = loader_data.get(video_key)
            if page_data is None:
                print(f"[WARN] page_data is None for key: {video_key}", file=sys.stderr)
                for k, v in loader_data.items():
                    print(f"[DEBUG] key={k}, type={type(v).__name__}", file=sys.stderr)
                    if isinstance(v, dict):
                        print(f"[DEBUG]   sub-keys: {list(v.keys())[:20]}", file=sys.stderr)
                return {"raw_keys": list(loader_data.keys()), "source": "ROUTER_DATA", "html_length": len(res.text)}

            print(f"[INFO] video page data keys: {list(page_data.keys()) if isinstance(page_data, dict) else type(page_data).__name__}", file=sys.stderr)

            video_info_res = page_data.get("videoInfoRes", {})
            if not video_info_res:
                for k, v in page_data.items():
                    print(f"[DEBUG] page_data key={k}, type={type(v).__name__}", file=sys.stderr)
                    if isinstance(v, dict):
                        print(f"[DEBUG]   sub-keys: {list(v.keys())[:20]}", file=sys.stderr)
                        if "item_list" in v:
                            video_info_res = v
                            break
            item_list = video_info_res.get("item_list", [])

            if not item_list:
                return {"raw_keys": list(page_data.keys()), "source": "ROUTER_DATA", "html_length": len(res.text)}

            video_info = item_list[0]
            author = video_info.get("author", {})
            statistics = video_info.get("statistics", {})
            video = video_info.get("video", {})

            result = {
                "video_id": video_id,
                "desc": video_info.get("desc", ""),
                "author": {
                    "nickname": author.get("nickname", ""),
                    "uid": author.get("uid", ""),
                    "sec_uid": author.get("sec_uid", ""),
                    "signature": author.get("signature", ""),
                    "avatar_thumb": author.get("avatar_thumb", {}).get("url_list", [""])[0] if author.get("avatar_thumb") else "",
                    "follower_count": author.get("follower_count", 0),
                    "following_count": author.get("following_count", 0),
                    "aweme_count": author.get("aweme_count", 0),
                    "favoriting_count": author.get("favoriting_count", 0),
                },
                "statistics": {
                    "digg_count": statistics.get("digg_count", 0),
                    "comment_count": statistics.get("comment_count", 0),
                    "share_count": statistics.get("share_count", 0),
                    "play_count": statistics.get("play_count", 0),
                    "collect_count": statistics.get("collect_count", 0),
                },
                "video": {
                    "duration": video.get("duration", 0),
                    "width": video.get("width", 0),
                    "height": video.get("height", 0),
                    "ratio": video.get("ratio", ""),
                    "cover": video.get("cover", {}).get("url_list", [""])[0] if video.get("cover") else "",
                    "dynamic_cover": video.get("dynamic_cover", {}).get("url_list", [""])[0] if video.get("dynamic_cover") else "",
                    "play_addr": video.get("play_addr", {}).get("url_list", [""])[0] if video.get("play_addr") else "",
                },
                "create_time": video_info.get("create_time", 0),
                "tags": [],
                "source": "ROUTER_DATA",
            }

            text_extra = video_info.get("text_extra", [])
            for tag in text_extra:
                if tag.get("hashtag_name"):
                    result["tags"].append(tag["hashtag_name"])

            music = video_info.get("music", {})
            if music:
                result["music"] = {
                    "title": music.get("title", ""),
                    "author": music.get("author", ""),
                    "play_url": music.get("play_url", {}).get("url_list", [""])[0] if music.get("play_url") else "",
                }

            return result

        except requests.Timeout:
            print(f"[ERROR] get_video_info timeout (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
        except requests.ConnectionError as e:
            print(f"[ERROR] get_video_info connection error: {e} (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parse error: {e}", file=sys.stderr)
            return {"error": f"JSON parse error: {e}"}
        except Exception as e:
            print(f"[ERROR] get_video_info failed: {e} (attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)

    return {"error": "All retries exhausted"}


def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if len(sys.argv) < 2:
        print("Usage: python extract_douyin.py <douyin_url>", file=sys.stderr)
        sys.exit(1)
    short_url = sys.argv[1]
    if not short_url.strip():
        print(json.dumps({"error": "Empty URL provided"}, ensure_ascii=False, indent=2))
        sys.exit(1)
    video_id, real_url = get_video_id(short_url)
    print(f"Video ID: {video_id}", file=sys.stderr)
    print(f"Real URL: {real_url}", file=sys.stderr)
    if video_id:
        info = get_video_info(video_id)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "Failed to get video ID", "input_url": short_url}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
