import os
import sys
import json
import logging
import mimetypes
import uuid
from pathlib import Path
from datetime import datetime

# Directories, file extensions, and specific filenames to skip
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".git"}
SKIP_EXTS = {
    ".xlsx",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".exe",
    ".dll",
    ".pyc",
    ".so",
}
SKIP_FILES = {".gitignore"}

# Global trace ID for this execution
TRACE_ID = str(uuid.uuid4())


class OTELJsonFormatter(logging.Formatter):
    def format(self, record):
        base = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity_text": record.levelname,
            "severity_number": self.map_severity(record.levelno),
            "message": record.getMessage(),
            "trace_id": TRACE_ID,
            "logger.name": record.name,
            "code.function": record.funcName,
        }
        if hasattr(record, "extra"):
            base.update(record.extra)
        return json.dumps(base)

    @staticmethod
    def map_severity(level):
        return {
            logging.DEBUG: 5,
            logging.INFO: 9,
            logging.WARNING: 13,
            logging.ERROR: 17,
            logging.CRITICAL: 21,
        }.get(level, 1)


# Configure logger
logger = logging.getLogger("repo_indexer")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(OTELJsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def log_info(message, **kwargs):
    logger.info(message, extra={"extra": kwargs})


def log_warning(message, **kwargs):
    logger.warning(message, extra={"extra": kwargs})


def log_error(message, **kwargs):
    logger.error(message, extra={"extra": kwargs})


def is_binary_file(file_path: Path) -> bool:
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is not None and not mime_type.startswith("text"):
        log_info("Skipping binary file", file_path=str(file_path))
        return True
    return False


def should_skip_file(file_path: Path, metrics: dict) -> bool:
    if file_path.suffix.lower() in SKIP_EXTS:
        log_info(
            "Skipping by extension", file_name=file_path.name, file_path=str(file_path)
        )
        metrics["skipped"] += 1
        return True
    if file_path.name in SKIP_FILES:
        log_info(
            "Skipping by filename", file_name=file_path.name, file_path=str(file_path)
        )
        metrics["skipped"] += 1
        return True
    if is_binary_file(file_path):
        metrics["skipped"] += 1
        return True
    return False


def read_text_file(file_path: Path, metrics: dict, max_chars: int = 5000) -> str | None:
    try:
        content = file_path.read_text(encoding="utf-8")
        if len(content) > max_chars:
            log_info("Truncating large file", file_path=str(file_path))
            content = content[:max_chars] + "\n...[truncated]"
        return content
    except Exception as e:
        log_warning("Unreadable file", file_path=str(file_path), error=str(e))
        metrics["errors"] += 1
        return None


def index_repo(repo_path: str | Path) -> str:
    repo_path = Path(repo_path).resolve()
    metrics = {"indexed": 0, "skipped": 0, "errors": 0}
    log_info(
        "Indexing repository", event_name="repo_scan_start", file_path=str(repo_path)
    )

    file_index = []

    for root, dirs, files in os.walk(repo_path):
        original_dirs = list(dirs)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        skipped_dirs = set(original_dirs) - set(dirs)
        for d in skipped_dirs:
            log_info("Skipping directory", file_name=d, file_path=str(Path(root) / d))

        for file in files:
            file_path = Path(root) / file
            if should_skip_file(file_path, metrics):
                continue

            content = read_text_file(file_path, metrics)
            if content is not None:
                rel_path = file_path.relative_to(repo_path)
                log_info(
                    "Indexed file",
                    file_path=str(file_path),
                    file_name=file,
                    file_rel_path=str(rel_path),
                )
                file_index.append(f"### {rel_path}\n{content}")
                metrics["indexed"] += 1

    result = "\n".join(file_index)
    metrics["char_count"] = len(result)

    log_info(
        "Indexing complete",
        event_name="repo_scan_end",
        file_indexed=metrics["indexed"],
        file_skipped=metrics["skipped"],
        file_errors=metrics["errors"],
        char_count=metrics["char_count"],
    )

    return result


def main():
    print(index_repo("."))


if __name__ == "__main__":
    main()
