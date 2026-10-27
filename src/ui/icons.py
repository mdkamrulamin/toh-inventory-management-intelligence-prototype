"""Load local role illustrations for native Streamlit Markdown."""

from base64 import b64encode
from functools import lru_cache

from src.config import PROJECT_ROOT, ROLE_ICON_FILES

@lru_cache(maxsize=4)
def role_icon_data_uri(role_id: str) -> str:
    """Embed a local PNG without depending on an external image server."""
    
    icon_path = (PROJECT_ROOT / "assets" / "icons" / ROLE_ICON_FILES[role_id])
    if not icon_path.is_file():
        raise FileNotFoundError(
            f"Role icon not found: {icon_path}. Add the correctly named PNG under assets/icons."
        )
        
    encoded_icon = b64encode(icon_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_icon}"