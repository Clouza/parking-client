#!/usr/bin/env python3
"""
role-based access control module
manages permissions for different camera roles
"""

from enum import Enum
from typing import Set, Dict

class Role(Enum):
    """camera roles"""
    ENTRANCE = "entrance"
    EXIT = "exit"
    MONITORING = "monitoring"
    ADMIN = "admin"

class Permission(Enum):
    """available permissions"""
    STREAM_VIDEO = "stream_video"
    DETECT_VEHICLE = "detect_vehicle"
    CAPTURE_IMAGE = "capture_image"
    ACCESS_API = "access_api"
    MODIFY_CONFIG = "modify_config"
    VIEW_LOGS = "view_logs"

class RBACManager:
    """role-based access control manager"""

    def __init__(self):
        """initialize rbac with role permissions"""
        self.role_permissions: Dict[Role, Set[Permission]] = {
            Role.ENTRANCE: {
                Permission.STREAM_VIDEO,
                Permission.DETECT_VEHICLE,
                Permission.CAPTURE_IMAGE,
                Permission.ACCESS_API
            },
            Role.EXIT: {
                Permission.STREAM_VIDEO,
                Permission.DETECT_VEHICLE,
                Permission.CAPTURE_IMAGE,
                Permission.ACCESS_API
            },
            Role.MONITORING: {
                Permission.STREAM_VIDEO,
                Permission.CAPTURE_IMAGE,
                Permission.ACCESS_API
            },
            Role.ADMIN: {
                Permission.STREAM_VIDEO,
                Permission.DETECT_VEHICLE,
                Permission.CAPTURE_IMAGE,
                Permission.ACCESS_API,
                Permission.MODIFY_CONFIG,
                Permission.VIEW_LOGS
            }
        }

    def has_permission(self, role: str, permission: str) -> bool:
        """
        check if role has specific permission

        args:
            role: camera role string
            permission: permission to check

        returns:
            True if role has permission, False otherwise
        """
        try:
            role_enum = Role(role.lower())
            permission_enum = Permission(permission.lower())
            return permission_enum in self.role_permissions.get(role_enum, set())
        except (ValueError, KeyError):
            return False

    def get_permissions(self, role: str) -> Set[str]:
        """
        get all permissions for a role

        args:
            role: camera role string

        returns:
            set of permission strings
        """
        try:
            role_enum = Role(role.lower())
            permissions = self.role_permissions.get(role_enum, set())
            return {perm.value for perm in permissions}
        except ValueError:
            return set()

    def validate_action(self, role: str, action: str) -> bool:
        """
        validate if role can perform action

        args:
            role: camera role string
            action: action to validate

        returns:
            True if allowed, False otherwise
        """
        action_permission_map = {
            'start_streaming': Permission.STREAM_VIDEO,
            'detect_vehicle': Permission.DETECT_VEHICLE,
            'capture_frame': Permission.CAPTURE_IMAGE,
            'api_request': Permission.ACCESS_API,
            'update_config': Permission.MODIFY_CONFIG,
            'read_logs': Permission.VIEW_LOGS
        }

        required_permission = action_permission_map.get(action)
        if not required_permission:
            return False

        return self.has_permission(role, required_permission.value)