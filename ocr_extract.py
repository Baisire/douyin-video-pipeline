import sys
import os
import json
import time
from rapidocr_onnxruntime import RapidOCR

_ocr_engine = None

def get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine

def extract(image_path, min_conf=0.5):
    if not os.path.exists(image_path):
        return None
    ocr = get_ocr()
    result, _ = ocr(image_path)
    if not result:
        return []
    return [{"text": item[1], "confidence": round(item[2], 4),
             "bbox": [[round(p[0], 1), round(p[1], 1)] for p in item[0]]}
            for item in result if item[2] >= min_conf]

def batch_extract(paths, min_conf=0.5):
    t0 = time.time()
    results = {}
    for p in paths:
        r = extract(p, min_conf)
        if r is not None:
            results[p] = r
    elapsed = round(time.time() - t0, 2)
    return results, elapsed

def deduplicate(results):
    seen = set()
    merged = []
    for path, items in results.items():
        for item in items:
            t = item["text"]
            if t not in seen:
                seen.add(t)
                merged.append({"text": t, "confidence": item["confidence"],
                                "source": os.path.basename(path)})
    return merged

def main():
    if len(sys.argv) < 2:
        print("Usage: python ocr_extract.py <image_path> [image_path2 ...] [--json] [--min-conf 0.5]")
        sys.exit(1)

    args = sys.argv[1:]
    output_json = "--json" in args
    min_conf = 0.5
    if "--min-conf" in args:
        idx = args.index("--min-conf")
        min_conf = float(args[idx + 1])
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]
    args = [a for a in args if a != "--json"]

    results, elapsed = batch_extract(args, min_conf)
    deduped = deduplicate(results)

    if output_json:
        out = {"elapsed_seconds": elapsed, "frame_count": len(results),
               "total_texts": len(deduped), "frames": {}}
        for path, items in results.items():
            out["frames"][os.path.basename(path)] = items
        out["deduplicated"] = deduped
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for path, items in results.items():
            print(f"\n=== {os.path.basename(path)} ===")
            for item in items:
                bar = "█" * int(item["confidence"] * 10)
                print(f"  [{bar}] {item['text']} ({item['confidence']})")
        print(f"\n=== DEDUPLICATED ({len(deduped)} texts, {elapsed}s) ===")
        for item in deduped:
            print(f"  {item['text']}")

if __name__ == "__main__":
    main()
