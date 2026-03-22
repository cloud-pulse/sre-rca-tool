import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from core.logger import get_logger
import hashlib
import json
import time
from pathlib import Path
from flags import (
    LLM_CACHE_ENABLED,
    LLM_CACHE_TTL
)

log = get_logger("llm_cache")

CACHE_DIR = ".llm_cache"

class LLMCache:

    def __init__(self):
        # Create cache directory if it
        # does not exist
        Path(CACHE_DIR).mkdir(
            exist_ok=True
        )
        log.step(
            f"LLM cache dir ready: {CACHE_DIR}"
        )

    def _make_key(self,
              prompt: str,
              mode: str,
              query: str = "") -> str:
        # Generate a cache key from:
        #   - First 2000 chars of prompt
        #     (enough to be unique per log)
        #   - mode (baseline or rag)
        #   - user query
        # Hash with MD5 for short filename
        content = f"{mode}:{query}:{prompt[:2000]}"
        return hashlib.md5(
            content.encode()
        ).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(
            CACHE_DIR, f"{key}.json"
        )

    def get(self, prompt: str,
        mode: str,
        query: str = "") -> dict | None:
        # Return cached result if:
        #   - LLM_CACHE_ENABLED is True
        #   - Cache file exists
        #   - Cache file is not expired
        #     (age < LLM_CACHE_TTL seconds)
        #
        # Return None if not cached or expired

        if not LLM_CACHE_ENABLED:
            log.debug("Cache disabled by flag")
            return None

        key = self._make_key(prompt, mode, query)
        path = self._cache_path(key)

        if not os.path.exists(path):
            log.debug(
                f"Cache miss: {key[:8]}..."
            )
            return None

        try:
            with open(path, "r") as f:
                cached = json.load(f)

            # Check TTL
            cached_at = cached.get(
                "_cached_at", 0
            )
            age = time.time() - cached_at

            if age > LLM_CACHE_TTL:
                log.debug(
                    f"Cache expired: "
                    f"{int(age)}s old "
                    f"(TTL={LLM_CACHE_TTL}s)"
                )
                os.remove(path)
                return None

            log.debug(
                f"Cache hit: {key[:8]}... "
                f"({int(age)}s old)"
            )
            # Remove internal metadata
            # before returning
            result = {
                k: v for k, v in cached.items()
                if not k.startswith("_")
            }
            result["from_cache"] = True
            return result

        except Exception as e:
            log.debug(f"Cache read error: {e}")
            return None

    def set(self, prompt: str,
        mode: str,
        result: dict,
        query: str = ""):
        # Save result to cache
        # Add metadata fields prefixed with _
        # Skip if caching is disabled

        if not LLM_CACHE_ENABLED:
            return

        key = self._make_key(prompt, mode, query)
        path = self._cache_path(key)

        try:
            save_data = dict(result)
            save_data["_cached_at"] = time.time()
            save_data["_mode"] = mode
            save_data["_key"] = key

            with open(path, "w") as f:
                json.dump(save_data, f, indent=2)

            log.debug(
                f"Cached result: {key[:8]}..."
            )

        except Exception as e:
            log.debug(f"Cache write error: {e}")

    def clear(self,
              older_than_seconds: int = 0):
        # Delete cache files
        # If older_than_seconds > 0:
        #   only delete files older than that
        # If older_than_seconds == 0:
        #   delete ALL cache files
        #
        # Return count of deleted files

        deleted = 0
        try:
            for f in Path(CACHE_DIR).glob(
                "*.json"
            ):
                if older_than_seconds > 0:
                    age = (
                        time.time() -
                        f.stat().st_mtime
                    )
                    if age < older_than_seconds:
                        continue
                f.unlink()
                deleted += 1
            log.step(
                f"Cache cleared: "
                f"{deleted} files deleted"
            )
        except Exception as e:
            log.error(
                f"Cache clear error: {e}"
            )
        return deleted

    def stats(self) -> dict:
        # Return cache statistics:
        # {
        #   "enabled": True/False,
        #   "cache_dir": ".llm_cache",
        #   "total_entries": N,
        #   "total_size_kb": N,
        #   "ttl_seconds": N,
        #   "oldest_entry_age": N (seconds),
        #   "newest_entry_age": N (seconds)
        # }
        try:
            files = list(
                Path(CACHE_DIR).glob("*.json")
            )
            total_size = sum(
                f.stat().st_size
                for f in files
            )
            ages = [
                time.time() - f.stat().st_mtime
                for f in files
            ]
            return {
                "enabled": LLM_CACHE_ENABLED,
                "cache_dir": CACHE_DIR,
                "total_entries": len(files),
                "total_size_kb": round(
                    total_size / 1024, 1
                ),
                "ttl_seconds": LLM_CACHE_TTL,
                "oldest_entry_age": int(
                    max(ages)
                ) if ages else 0,
                "newest_entry_age": int(
                    min(ages)
                ) if ages else 0,
            }
        except Exception:
            return {
                "enabled": LLM_CACHE_ENABLED,
                "cache_dir": CACHE_DIR,
                "total_entries": 0,
                "total_size_kb": 0,
                "ttl_seconds": LLM_CACHE_TTL,
                "oldest_entry_age": 0,
                "newest_entry_age": 0,
            }


if __name__ == "__main__":

    print("=== Task C — LLM Cache Test ===\n")

    cache = LLMCache()

    print("--- Test 1: Cache stats (empty) ---")
    stats = cache.stats()
    print(f"Entries: {stats['total_entries']}")
    print(f"Enabled: {stats['enabled']}")

    print("\n--- Test 2: Cache miss ---")
    result = cache.get(
        "test prompt content", "baseline"
    )
    print(
        f"Cache miss returned: {result} "
        f"(should be None)"
    )

    print("\n--- Test 3: Cache set + get ---")
    mock_result = {
        "mode": "baseline",
        "root_cause": "DB connection pool",
        "confidence": 75,
        "suggested_fixes": []
    }
    cache.set(
        "test prompt content",
        "baseline",
        mock_result
    )
    retrieved = cache.get(
        "test prompt content", "baseline"
    )
    if retrieved:
        print(
            f"Cache hit: "
            f"root_cause = "
            f"{retrieved['root_cause']}"
        )
        print(
            f"from_cache = "
            f"{retrieved.get('from_cache')}"
        )
    else:
        print("Cache get failed — CHECK!")

    print("\n--- Test 4: Cache stats ---")
    stats = cache.stats()
    print(f"Entries: {stats['total_entries']}")
    print(
        f"Size: {stats['total_size_kb']} KB"
    )

    print("\n--- Test 5: Different keys ---")
    cache.set(
        "different prompt", "rag", mock_result
    )
    stats = cache.stats()
    print(
        f"Entries after 2nd set: "
        f"{stats['total_entries']} "
        f"(should be 2)"
    )

    print("\n--- Test 6: Clear cache ---")
    deleted = cache.clear(0)
    print(f"Deleted: {deleted} entries")
    stats = cache.stats()
    print(
        f"Entries after clear: "
        f"{stats['total_entries']} "
        f"(should be 0)"
    )

    print("\nTask C — Cache tests OK")
