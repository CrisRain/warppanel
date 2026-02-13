import os

def get_app_version():
    """Reads the application version from the VERSION file in the project root."""
    try:
        # Assuming VERSION file is in the project root (d:\Projects\warp-panel\VERSION)
        # and this file is in d:\Projects\warp-panel\backend\app\utils
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        version_file = os.path.join(base_dir, 'VERSION')
        
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                return f.read().strip()
        return "Unknown"
    except Exception:
        return "Unknown"
