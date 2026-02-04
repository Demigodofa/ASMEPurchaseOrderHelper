from pathlib import Path


def freeze_manifest_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "sectionII_partA_data_digitized" / "rebuild" / "final_freeze_manifest.json"


def ensure_not_frozen() -> None:
    path = freeze_manifest_path()
    if path.exists():
        raise SystemExit(
            f"Corpus is frozen; refusing to run. Remove {path} to proceed."
        )
