"""The built Command Center, served from the same origin as the API."""

from .spa import SinglePageApp, mount_frontend

__all__ = ["SinglePageApp", "mount_frontend"]
