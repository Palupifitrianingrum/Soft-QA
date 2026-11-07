from pathlib import Path

from .config import settings


def project_dir(project_id: int) -> Path:
    return settings.data_dir / "projects" / str(project_id)


def project_src(project_id: int) -> Path:
    return project_dir(project_id) / "src"
