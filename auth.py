#!/usr/bin/env python3
"""
authentication module for parking client
handles jwt token generation and validation
"""

import jwt
import time
from datetime import datetime, timedelta
from typing import Optional, Dict

class AuthManager:
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        """
        initialize auth manager

        args:
            secret_key: secret key for jwt signing
            algorithm: jwt algorithm (default: HS256)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.token_expiry = 3600  # 1 hour in seconds

    def generate_token(self, camera_id: str, camera_role: str) -> str:
        """
        generate jwt token for camera client

        args:
            camera_id: unique camera identifier
            camera_role: camera role (entrance/exit/monitoring)

        returns:
            jwt token string
        """
        payload = {
            'camera_id': camera_id,
            'camera_role': camera_role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(seconds=self.token_expiry)
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def validate_token(self, token: str) -> Optional[Dict]:
        """
        validate jwt token

        args:
            token: jwt token to validate

        returns:
            decoded payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def refresh_token(self, token: str) -> Optional[str]:
        """
        refresh expired token

        args:
            token: existing jwt token

        returns:
            new token if valid, None otherwise
        """
        payload = self.validate_token(token)
        if payload:
            return self.generate_token(
                payload['camera_id'],
                payload['camera_role']
            )
        return None