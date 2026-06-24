import subprocess
import sys
import os
import json
import time
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(SCRIPT_DIR, "screenshots")

def ensure_dir():
    if os.path.exists(SCREENSHOTS_DIR):
        shutil.rmtree(SCREENSHOTS_DIR)
    os.makedirs(SCREENSHOTS_DIR)

def run_ocr(image_paths, min_conf=0.5):
    if not image_paths:
        return {"frames": {}, "deduplicated": [], "elapsed_seconds": 0, "total_texts": 0}
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "ocr_extract.py")] + image_paths + ["--json", "--min-conf", str(min_conf)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(f"[ERROR] OCR failed: {result.stderr}", file=sys.stderr)
        return {"frames": {}, "deduplicated": [], "elapsed_seconds": 0, "total_texts": 0}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"[ERROR] OCR output parse failed", file=sys.stderr)
        return {"frames": {}, "deduplicated": [], "elapsed_seconds": 0, "total_texts": 0}

def build_timeline(ocr_result, interval):
    frames = ocr_result.get("frames", {})
    timeline = []
    sorted_files = sorted(frames.keys())
    for i, fname in enumerate(sorted_files):
        ts_start = i * interval
        ts_end = (i + 1) * interval
        items = frames[fname]
        texts = [item["text"] for item in items]
        if texts:
            timeline.append({
                "time_range": f"{ts_start:02d}:{(ts_start % 60):02d}-{ts_end:02d}:{(ts_end % 60):02d}",
                "texts": texts
            })
    return timeline

def generate_report(metadata, timeline, ocr_result, deduped_texts):
    lines = []
    lines.append("# 视频内容分析报告\n")
    lines.append("## 一、视频基本信息\n")
    lines.append("| 项目 | 信息 |")
    lines.append("|------|------|")
    for k, v in metadata.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    if timeline:
        lines.append("## 二、视频画面文字提取（OCR逐帧）\n")
        for entry in timeline:
            lines.append(f"### {entry['time_range']}")
            for t in entry["texts"]:
                lines.append(f"- {t}")
            lines.append("")
    lines.append("## 三、全部提取文字（去重）\n")
    for t in deduped_texts:
        lines.append(f"- {t}")
    lines.append("")
    lines.append(f"## 四、统计信息\n")
    lines.append(f"- OCR帧数: {ocr_result.get('frame_count', 0)}")
    lines.append(f"- 去重文字数: {ocr_result.get('total_texts', 0)}")
    lines.append(f"- OCR耗时: {ocr_result.get('elapsed_seconds', 0)}秒")
    return "\n".join(lines)

def main():
    if len(sys.argv) < 2:
        print("Usage: python video_ocr_pipeline.py <screenshot1.png> [screenshot2.png ...] [--interval 3] [--min-conf 0.5] [--metadata-json '{}']")
        print("\nThis script processes screenshots from video frames and generates a structured report.")
        print("Screenshots should be captured beforehand using browser tools.")
        sys.exit(1)

    args = sys.argv[1:]
    interval = 3
    min_conf = 0.5
    metadata = {}
    image_paths = []

    i = 0
    while i < len(args):
        if args[i] == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])
            i += 2
        elif args[i] == "--min-conf" and i + 1 < len(args):
            min_conf = float(args[i + 1])
            i += 2
        elif args[i] == "--metadata-json" and i + 1 < len(args):
            metadata = json.loads(args[i + 1])
            i += 2
        elif args[i].endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
            image_paths.append(args[i])
            i += 1
        else:
            i += 1

    if not image_paths:
        print("[ERROR] No image files provided", file=sys.stderr)
        sys.exit(1)

    t0 = time.time()
    print(f"[INFO] Processing {len(image_paths)} screenshots (interval={interval}s, min_conf={min_conf})...")

    ocr_result = run_ocr(image_paths, min_conf)
    timeline = build_timeline(ocr_result, interval)
    deduped_texts = [item["text"] for item in ocr_result.get("deduplicated", [])]

    report = generate_report(metadata, timeline, ocr_result, deduped_texts)
    total_time = round(time.time() - t0, 2)

    report_path = os.path.join(SCRIPT_DIR, "video_analysis_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[INFO] Report saved to {report_path}")
    print(f"[INFO] Total pipeline time: {total_time}s")
    print(f"[INFO] Frames: {ocr_result.get('frame_count', 0)}, Texts: {ocr_result.get('total_texts', 0)}")

if __name__ == "__main__":
    main()
