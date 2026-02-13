import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    _instance = None
    
    def __init__(self):
        # Allow overriding via env (useful for docker vs local dev)
        data_dir = os.getenv("WARP_DATA_DIR", "/app/data")
        self._config_file = os.path.join(data_dir, "config.json")
        
        self._config = {
            "socks5_port": 1080,
            "panel_port": 8000,
            "panel_password": "",  # Empty means disabled/no auth

        }
        self.load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ConfigManager()
        return cls._instance

    def load(self):
        """Load configuration from disk."""
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, "r") as f:
                    data = json.load(f)
                    self._config.update(data)
                logger.info(f"Configuration loaded from {self._config_file}")
            except Exception as e:
                logger.error(f"Failed to load configuration from {self._config_file}: {e}")
        else:
            logger.info(f"No configuration file found at {self._config_file}, using defaults.")
            # Verify if env vars set initial password if config doesn't exist
            env_pass = os.getenv("PANEL_PASSWORD")
            if env_pass:
                self._config["panel_password"] = env_pass
                self.save() # Save it so it persists

    def save(self):
        """Save configuration to disk."""
        try:
            os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
            with open(self._config_file, "w") as f:
                json.dump(self._config, f, indent=4)
            logger.info(f"Configuration saved to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value
        self.save()

    # Convenience accessors
    @property
    def socks5_port(self) -> int:
        return int(self._config.get("socks5_port", 1080))

    @property
    def panel_port(self) -> int:
        return int(self._config.get("panel_port", 8000))

    @property
    def panel_password(self) -> str:
        return self._config.get("panel_password", "")
        

