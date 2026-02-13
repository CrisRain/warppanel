import os
import json
import logging
import shutil
import subprocess
import requests
import platform
import zipfile
import stat
import re
from typing import List, Optional, Dict
from .config_controller import ConfigManager

logger = logging.getLogger(__name__)

class KernelVersionManager:
    _instance = None
    
    def __init__(self):
        # Base directory for data
        self.base_dir = os.getenv("WARP_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
        self.kernels_dir = os.path.join(self.base_dir, "kernels")
        
        # Ensure directories exist
        os.makedirs(self.kernels_dir, exist_ok=True)
        
        self.config_mgr = ConfigManager.get_instance()
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = KernelVersionManager()
        return cls._instance

    def list_versions(self, backend: str) -> List[str]:
        """List available versions for a backend"""
        if backend == "official":
            return ["System Default"]
            
        backend_dir = os.path.join(self.kernels_dir, backend)
        if not os.path.exists(backend_dir):
            return []
            
        versions = []
        try:
            for entry in os.scandir(backend_dir):
                if entry.is_dir() and not entry.name.startswith('.'):
                    versions.append(entry.name)
        except Exception as e:
            logger.error(f"Error listing versions for {backend}: {e}")
            
        return sorted(versions, reverse=True)

    def get_active_version(self, backend: str) -> Optional[str]:
        """Get the currently selected version for a backend"""
        if backend == "official":
            try:
                # Try to get real version
                result = subprocess.run(["warp-cli", "--version"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                pass
            return "System Default"
        
        # Use ConfigManager
        return self.config_mgr.get(f"{backend}_version")

    def set_active_version(self, backend: str, version: str) -> bool:
        """Set the active version for a backend"""
        if backend == "official":
            return False 
            
        # Verify version exists
        version_path = os.path.join(self.kernels_dir, backend, version)
        if not os.path.exists(version_path):
            logger.error(f"Version {version} not found for {backend}")
            return False
            
        # Update config via manager
        self.config_mgr.set(f"{backend}_version", version)
        
        # Update symlink if on Linux and backend is usque
        if os.name == 'posix' and backend == 'usque':
            self._update_symlink(backend, version)
            
        return True

    def _update_symlink(self, backend: str, version: str):
        """Update system symlink for the backend"""
        target_path = self.get_binary_path(backend)
        symlink_path = f"/usr/local/bin/{backend}"
        
        try:
            if os.path.islink(symlink_path) or os.path.exists(symlink_path):
                os.remove(symlink_path)
            
            os.symlink(target_path, symlink_path)
            logger.info(f"Updated symlink {symlink_path} -> {target_path}")
        except Exception as e:
            logger.error(f"Failed to update symlink: {e}")

    def get_binary_path(self, backend: str) -> str:
        """Get the executable path for the current backend version"""
        if backend == "official":
            return "warp-cli" # Use system path
            
        active_version = self.get_active_version(backend)
        if not active_version:
            # Fallback to system path if no version selected
            return backend 
            
        binary_name = backend
        if os.name == 'nt':
            binary_name += ".exe"
            
        binary_path = os.path.join(self.kernels_dir, backend, active_version, binary_name)
        
        if os.path.exists(binary_path):
            return binary_path
            
        logger.warning(f"Binary not found at {binary_path}, falling back to system path")
        return backend

    def get_installed_version_info(self, backend: str = "usque") -> Dict:
        """
        Get version info for the currently active backend.
        """
        binary_path = self.get_binary_path(backend)
        version_info = {
            "version": "Unknown",
            "is_latest": False,
            "latest_version": None,
            "update_available": False
        }
        
        # 1. Get local installed version
        try:
            cmd = [binary_path, "version"]
            # On windows, sometimes full path is needed or current dir behavior differs
            cwd = os.path.dirname(binary_path) if os.path.isabs(binary_path) else None
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2, cwd=cwd)
            if result.returncode == 0:
                output = result.stdout.strip()
                match = re.search(r'version\s+v?(\d+\.\d+\.\d+)', output, re.IGNORECASE)
                if match:
                    version_info["version"] = match.group(1)
                else:
                    match = re.search(r'v?(\d+\.\d+\.\d+)', output)
                    if match:
                        version_info["version"] = match.group(1)
                    else:
                         version_info["version"] = output
        except Exception as e:
            logger.debug(f"Failed to get local version for {backend}: {e}")
            active = self.get_active_version(backend)
            if active:
                 version_info["version"] = active.replace("v", "")

        # 2. Check cached latest version
        latest_cache = self.config_mgr.get(f"{backend}_latest_version")
        if latest_cache:
            version_info["latest_version"] = latest_cache
            if version_info["version"] != "Unknown" and latest_cache != version_info["version"]:
                 version_info["update_available"] = True
                 
        return version_info

    def check_for_updates(self, backend: str = "usque") -> Optional[str]:
        """
        Check GitHub for latest release.
        """
        if backend != "usque":
            return None
            
        repo = "Diniboy1123/usque"
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                tag_name = data.get("tag_name", "").lstrip("v")
                if tag_name:
                    # Update cache via manager
                    self.config_mgr.set(f"{backend}_latest_version", tag_name)
                    logger.info(f"Latest {backend} version: {tag_name}")
                    return tag_name
        except Exception as e:
            logger.error(f"Failed to check updates for {backend}: {e}")
            
        return None

    def auto_update(self, backend: str = "usque") -> bool:
        """
        Check for updates and install if newer version available.
        """
        if backend != "usque":
            return False
            
        logger.info(f"Starting auto-update check for {backend}...")
        
        latest_version = self.check_for_updates(backend)
        if not latest_version:
            return False
            
        current_info = self.get_installed_version_info(backend)
        current_version = current_info.get("version")
        
        if current_version == latest_version:
            logger.info(f"{backend} is up to date ({current_version})")
            return False
            
        logger.info(f"New version available: {latest_version} (current: {current_version}). Downloading...")
        
        if self.download_and_install(backend, latest_version):
            logger.info(f"Switching to new version {latest_version}...")
            return self.set_active_version(backend, latest_version)
            
        return False

    def download_and_install(self, backend: str, version: str) -> bool:
        """
        Download binary from GitHub releases and install to kernels dir.
        """
        if backend != "usque":
            return False
            
        arch = platform.machine().lower()
        system = platform.system().lower()
        
        if system == "linux":
            os_name = "linux"
        elif system == "darwin":
            os_name = "darwin"
        elif system == "windows":
            os_name = "windows"
        else:
            logger.error(f"Unsupported OS: {system}")
            return False
            
        if arch in ["x86_64", "amd64"]:
            arch_name = "amd64"
        elif arch in ["aarch64", "arm64"]:
            arch_name = "arm64"
        else:
            logger.error(f"Unsupported architecture: {arch}")
            return False
            
        repo = "Diniboy1123/usque"
        api_url = f"https://api.github.com/repos/{repo}/releases/tags/v{version}"
        
        download_url = None
        asset_name = None
        
        try:
            resp = requests.get(api_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if os_name in name and arch_name in name:
                         download_url = asset.get("browser_download_url")
                         asset_name = asset.get("name")
                         break
        except Exception as e:
            logger.error(f"Failed to get release info: {e}")
            return False
            
        if not download_url:
            logger.error(f"No compatible asset found for {os_name}/{arch_name}")
            return False
            
        target_dir = os.path.join(self.kernels_dir, backend, version)
        
        if os.path.exists(target_dir):
            binary_name = backend + (".exe" if os_name == "windows" else "")
            if os.path.exists(os.path.join(target_dir, binary_name)):
                logger.info(f"Version {version} already installed")
                return True
        
        os.makedirs(target_dir, exist_ok=True)
        zip_path = os.path.join(target_dir, asset_name)
        
        logger.info(f"Downloading {download_url}...")
        try:
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        
            logger.info("Extracting...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
                
            os.remove(zip_path)
            
            if os_name != "windows":
                binary_path = os.path.join(target_dir, backend)
                if os.path.exists(binary_path):
                    st = os.stat(binary_path)
                    os.chmod(binary_path, st.st_mode | stat.S_IEXEC)
                else:
                    logger.error("Binary not found after extraction")
                    return False
                    
            logger.info(f"Successfully installed {backend} {version}")
            return True
            
        except Exception as e:
            logger.error(f"Download/Install failed: {e}")
            return False
        
    def adopt_system_installation(self, backend: str = "usque") -> bool:
        """
        If no versions are managed, check if system has the binary installed
        """
        if backend != "usque":
            return False
            
        versions = self.list_versions(backend)
        if versions:
            return False
            
        system_path = shutil.which(backend)
        if not system_path:
            if os.path.exists("/usr/local/bin/usque"):
                system_path = "/usr/local/bin/usque"
            else:
                return False
        
        logger.info(f"Found system installation of {backend} at {system_path}")
        
        try:
            cmd = [system_path, "version"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                output = result.stdout.strip()
                match = re.search(r'v?(\d+\.\d+\.\d+)', output)
                if match:
                    version = match.group(1)
                    logger.info(f"Detected system version: {version}")
                    
                    target_dir = os.path.join(self.kernels_dir, backend, version)
                    os.makedirs(target_dir, exist_ok=True)
                    
                    target_binary = os.path.join(target_dir, backend)
                    
                    shutil.copy2(system_path, target_binary)
                    
                    self.set_active_version(backend, version)
                    logger.info(f"Adopted system installation as managed version {version}")
                    return True
        except Exception as e:
            logger.error(f"Failed to adopt system installation: {e}")
            
        return False
