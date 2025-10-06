#!/usr/bin/env python3
"""
security logging module
logs security events and suspicious activities
"""

import logging
import json
from datetime import datetime
from typing import Dict, Optional
from enum import Enum

class SecurityEventType(Enum):
    """security event types"""
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_TOKEN = "invalid_token"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    CONFIG_CHANGE = "config_change"
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_FAILED = "connection_failed"

class SecurityLogger:
    """security event logger"""

    def __init__(self, log_file: str = "security.log"):
        """
        initialize security logger

        args:
            log_file: path to security log file
        """
        self.logger = logging.getLogger("security")
        self.logger.setLevel(logging.INFO)

        # file handler for security logs
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # json formatter
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}'
        )
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)

    def log_event(
        self,
        event_type: SecurityEventType,
        client_id: str,
        details: Optional[Dict] = None,
        severity: str = "INFO"
    ):
        """
        log security event

        args:
            event_type: type of security event
            client_id: client identifier
            details: additional event details
            severity: log severity level
        """
        event_data = {
            "event_type": event_type.value,
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details or {}
        }

        log_message = json.dumps(event_data)

        if severity == "ERROR":
            self.logger.error(log_message)
        elif severity == "WARNING":
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)

    def log_auth_success(self, client_id: str, role: str):
        """log successful authentication"""
        self.log_event(
            SecurityEventType.AUTH_SUCCESS,
            client_id,
            {"role": role}
        )

    def log_auth_failure(self, client_id: str, reason: str):
        """log authentication failure"""
        self.log_event(
            SecurityEventType.AUTH_FAILURE,
            client_id,
            {"reason": reason},
            severity="WARNING"
        )

    def log_rate_limit(self, client_id: str, endpoint: str):
        """log rate limit exceeded"""
        self.log_event(
            SecurityEventType.RATE_LIMIT_EXCEEDED,
            client_id,
            {"endpoint": endpoint},
            severity="WARNING"
        )

    def log_invalid_token(self, client_id: str):
        """log invalid token attempt"""
        self.log_event(
            SecurityEventType.INVALID_TOKEN,
            client_id,
            severity="WARNING"
        )

    def log_unauthorized_access(self, client_id: str, resource: str):
        """log unauthorized access attempt"""
        self.log_event(
            SecurityEventType.UNAUTHORIZED_ACCESS,
            client_id,
            {"resource": resource},
            severity="ERROR"
        )

    def log_suspicious_activity(self, client_id: str, activity: str):
        """log suspicious activity"""
        self.log_event(
            SecurityEventType.SUSPICIOUS_ACTIVITY,
            client_id,
            {"activity": activity},
            severity="ERROR"
        )

    def log_config_change(self, client_id: str, changes: Dict):
        """log configuration changes"""
        self.log_event(
            SecurityEventType.CONFIG_CHANGE,
            client_id,
            {"changes": changes}
        )

    def log_connection(self, client_id: str, success: bool, details: Optional[Dict] = None):
        """log connection attempt"""
        event_type = (
            SecurityEventType.CONNECTION_ESTABLISHED if success
            else SecurityEventType.CONNECTION_FAILED
        )
        severity = "INFO" if success else "WARNING"

        self.log_event(event_type, client_id, details, severity)