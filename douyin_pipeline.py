import sys
import os
import json
import subprocess
import argparse
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

VALID_CATEGORIES = ["嵌入式", "AI", "销售", "其他技能", "思维认知", "其它-待分类"]

VIEWING_SUGGESTION_TAG_MAP = {
    "建议观看原视频": "需观看原视频",
    "可仅读报告": "可仅读报告",
}

VALID_URL_PATTERNS = [
    r"https?://v\.douyin\.com/\S+",
    r"https?://www\.douyin\.com/video/\d+",
    r"https?://www\.iesdouyin\.com/share/video/\d+",
]

AI_PROMPT_TEMPLATE = """你是我的知识管理助手。我会使用skill获取视频信息，请严格按以下结构输出，不要添加任何额外开场或结尾。

## 核心总结
用 3-5 句中文概括视频最重要的内容，包含关键结论和数据。

## 知识点清单
- 要点1
- 要点2
- ...

## 观看建议
判断为以下两者之一，并给出 1 句话理由：
- 可仅读报告
- 建议观看原视频
（判断标准：若内容以概念讲解、观点、采访对话为主 → 可仅读报告；若包含大量屏幕操作演示、实物手工、图纸讲解、代码详细走读 → 建议观看原视频）

## 主题分类
从以下列表中选择唯一一个最匹配的分类：
嵌入式 | AI | 销售 | 其他技能 | 思维认知 | 其它-待分类

## 可执行行动
如果视频提供了可立即实践的步骤、练习或资源，逐条列出；若无则写"无"。"""

NOTE_TEMPLATE = """---
tags:
  - AI摘要
  - {viewing_tag}
主题: "{category}"
视频来源: "{original_url}"
日期: "{date}"
---

# {title}

## 核心总结
{summary}

## 知识点
{knowledge_points}

## 观看建议：{viewing_result}
理由：{viewing_reason}

## 行动清单
{actions}"""


def validate_url(url):
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    for pattern in VALID_URL_PATTERNS:
        if re.match(pattern, url):
            return url
    return None


def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:100] if len(name) > 100 else name


def run_extract_douyin(url):
    script_path = os.path.join(SCRIPT_DIR, "extract_douyin.py")
    if not os.path.exists(script_path):
        print(f"[ERROR] extract_douyin.py not found at: {script_path}", file=sys.stderr)
        return None
    cmd = [sys.executable, script_path, url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=30)
    except subprocess.TimeoutExpired:
        print("[ERROR] extract_douyin.py timed out after 30 seconds", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] Failed to run extract_douyin.py: {e}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"[ERROR] extract_douyin.py failed (exit code {result.returncode}): {result.stderr}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse extract_douyin output: {e}", file=sys.stderr)
        print(f"[DEBUG] Raw stdout (first 500 chars): {result.stdout[:500]}", file=sys.stderr)
        return None


def format_duration(duration_ms):
    if not duration_ms:
        return "未知"
    seconds = duration_ms / 1000
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def generate_ai_prompt(metadata, ocr_text=""):
    context_parts = []

    if metadata:
        title = metadata.get("desc", "未知标题")
        author = metadata.get("author", {}).get("nickname", "未知作者")
        duration = format_duration(metadata.get("video", {}).get("duration", 0))
        tags = ", ".join(metadata.get("tags", []))
        stats = metadata.get("statistics", {})

        context_parts.append(f"视频标题：{title}")
        context_parts.append(f"作者：{author}")
        context_parts.append(f"时长：{duration}")
        context_parts.append(f"标签：{tags}")
        context_parts.append(f"点赞数：{stats.get('digg_count', 0)}")
        context_parts.append(f"评论数：{stats.get('comment_count', 0)}")
        context_parts.append(f"分享数：{stats.get('share_count', 0)}")

    if ocr_text:
        context_parts.append("")
        context_parts.append("视频画面文字内容（OCR提取）：")
        context_parts.append(ocr_text)

    context = "\n".join(context_parts)

    full_prompt = f"{AI_PROMPT_TEMPLATE}\n\n---\n\n以下是视频的上下文信息：\n\n{context}"
    return full_prompt


def parse_ai_output(ai_text):
    result = {
        "summary": "",
        "knowledge_points": "",
        "viewing_result": "",
        "viewing_reason": "",
        "category": "其它-待分类",
        "actions": "无",
    }

    sections = {
        "核心总结": "summary",
        "知识点清单": "knowledge_points",
        "观看建议": "viewing_suggestion",
        "主题分类": "category",
        "可执行行动": "actions",
    }

    current_section = None
    lines = ai_text.strip().split("\n")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            section_name = stripped[3:].strip()
            for key, field in sections.items():
                if key in section_name:
                    current_section = field
                    break
            else:
                current_section = None
            continue

        if current_section == "summary" and stripped:
            result["summary"] += stripped + " "
        elif current_section == "knowledge_points":
            if stripped.startswith("- "):
                result["knowledge_points"] += stripped + "\n"
        elif current_section == "viewing_suggestion":
            if "建议观看原视频" in stripped:
                result["viewing_result"] = "建议观看原视频"
            elif "可仅读报告" in stripped:
                result["viewing_result"] = "可仅读报告"
            elif stripped.startswith("理由") or stripped.startswith("（"):
                reason = stripped
                if reason.startswith("理由：") or reason.startswith("理由:"):
                    reason = reason.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif reason.startswith("（"):
                    reason = reason.strip("（）").strip("()")
                if reason:
                    result["viewing_reason"] = reason
            elif stripped and not result["viewing_result"]:
                if "建议观看原视频" in stripped or "可仅读报告" in stripped:
                    pass
                elif not result["viewing_reason"]:
                    result["viewing_reason"] = stripped
        elif current_section == "category":
            for cat in VALID_CATEGORIES:
                if cat in stripped:
                    result["category"] = cat
                    break
        elif current_section == "actions":
            if stripped.startswith("- "):
                if result["actions"] == "无":
                    result["actions"] = ""
                result["actions"] += stripped + "\n"
            elif stripped == "无":
                result["actions"] = "无"
            elif stripped:
                if result["actions"] == "无":
                    result["actions"] = ""
                result["actions"] += f"- {stripped}\n"

    result["summary"] = result["summary"].strip()
    result["knowledge_points"] = result["knowledge_points"].strip()
    result["actions"] = result["actions"].strip()

    if not result["viewing_result"]:
        result["viewing_result"] = "可仅读报告"
    if not result["viewing_reason"]:
        result["viewing_reason"] = "内容以概念讲解为主"

    return result


def fill_note_template(parsed, metadata, original_url):
    viewing_tag = VIEWING_SUGGESTION_TAG_MAP.get(
        parsed["viewing_result"], "可仅读报告"
    )
    date_str = datetime.now().strftime("%Y-%m-%d")
    title = metadata.get("desc", "未知标题") if metadata else "未知标题"

    note = NOTE_TEMPLATE.format(
        viewing_tag=viewing_tag,
        category=parsed["category"],
        original_url=original_url,
        date=date_str,
        title=title,
        summary=parsed["summary"],
        knowledge_points=parsed["knowledge_points"],
        viewing_result=parsed["viewing_result"],
        viewing_reason=parsed["viewing_reason"],
        actions=parsed["actions"],
    )
    return note, date_str, title


def save_backup(note_content, filename, category):
    output_dir = os.path.join(SCRIPT_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    safe_name = sanitize_filename(filename)
    filepath = os.path.join(output_dir, safe_name)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(note_content)
    print(f"[INFO] Backup saved to: {filepath}", file=sys.stderr)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="抖音视频处理与Obsidian集成流水线")
    parser.add_argument("url", help="抖音视频URL")
    parser.add_argument("--metadata-only", action="store_true", help="仅提取元数据，跳过AI分析和笔记模板")
    parser.add_argument("--ocr-text", default="", help="已提取的OCR文本（可选）")
    parser.add_argument("--ai-output", default="", help="AI分析结果文本（可选，用于直接填充笔记模板）")
    parser.add_argument("--save-backup", action="store_true", help="将笔记保存到本地output目录作为备份")
    args = parser.parse_args()

    validated_url = validate_url(args.url)
    if not validated_url:
        print(json.dumps({"error": "无效的抖音视频链接", "input_url": args.url}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print("[INFO] Step 1: 提取视频元数据...", file=sys.stderr)
    metadata = run_extract_douyin(validated_url)

    if not metadata:
        print(json.dumps({"error": "元数据提取失败", "url": validated_url}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if "error" in metadata:
        print(json.dumps({"error": metadata["error"], "url": validated_url}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.metadata_only:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return

    original_url = validated_url
    real_url = metadata.get("video_id", "")
    if real_url:
        original_url = f"https://www.douyin.com/video/{real_url}"

    title = metadata.get("desc", "")
    author = metadata.get("author", {}).get("nickname", "")
    if not title:
        title = f"视频_{real_url or '未知'}"
        print(f"[WARN] 视频标题为空，使用占位标题: {title}", file=sys.stderr)
    if not author:
        print("[WARN] 作者信息为空，元数据不完整", file=sys.stderr)

    print("[INFO] Step 2: 生成AI分析提示词...", file=sys.stderr)
    ai_prompt = generate_ai_prompt(metadata, args.ocr_text)

    if args.ai_output:
        print("[INFO] Step 3: 使用提供的AI输出填充笔记模板...", file=sys.stderr)
        parsed = parse_ai_output(args.ai_output)
    else:
        print("[INFO] Step 3: 生成笔记模板（等待AI分析）...", file=sys.stderr)
        parsed = {
            "summary": "{{待AI分析填充}}",
            "knowledge_points": "{{待AI分析填充}}",
            "viewing_result": "可仅读报告",
            "viewing_reason": "{{待AI分析填充}}",
            "category": "其它-待分类",
            "actions": "无",
        }

    note_content, date_str, title = fill_note_template(parsed, metadata, original_url)
    safe_filename = sanitize_filename(f"{date_str}_{title}.md")

    output = {
        "metadata": metadata,
        "ai_prompt": ai_prompt,
        "note_content": note_content,
        "note_filename": safe_filename,
        "note_folder": "0-Inbox",
        "category": parsed["category"],
        "viewing_suggestion": parsed["viewing_result"],
        "original_url": original_url,
    }

    if args.save_backup:
        backup_path = save_backup(note_content, safe_filename, parsed["category"])
        output["backup_path"] = backup_path

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
