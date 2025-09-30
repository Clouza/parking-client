#!/usr/bin/env python3
"""
secure camera client with integrated security features
demonstrates usage of auth, rbac, rate limiting, and security logging
"""

import json
import logging
from streaming_client import StreamingClient
from auth import AuthManager
from rbac import RBACManager
from rate_limiter import RateLimiter, SlidingWindowRateLimiter
from security_logger import SecurityLogger
from security_headers import SecurityHeaders

class SecureCameraClient:
    """secure camera client with security features"""

    def __init__(self, config_path: str = "config.json"):
        """
        initialize secure camera client

        args:
            config_path: path to configuration file
        """
        # load configuration
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        # initialize security components
        self._initialize_security()

    def _initialize_security(self):
        """initialize security modules"""
        security_config = self.config.get('security', {})

        # jwt authentication
        jwt_secret = security_config.get('jwt_secret', 'default-secret-change-this')
        jwt_algorithm = security_config.get('jwt_algorithm', 'HS256')
        self.auth_manager = AuthManager(jwt_secret, jwt_algorithm)

        # role-based access control
        self.rbac_manager = RBACManager()

        # rate limiting
        rate_limit_config = security_config.get('rate_limiting', {})
        if rate_limit_config.get('enabled', True):
            self.rate_limiter = RateLimiter(
                requests_per_second=rate_limit_config.get('requests_per_second', 10),
                burst_size=rate_limit_config.get('burst_size', 20)
            )
            self.sliding_rate_limiter = SlidingWindowRateLimiter(
                max_requests=rate_limit_config.get('max_requests', 100),
                window_seconds=rate_limit_config.get('window_seconds', 60)
            )
        else:
            self.rate_limiter = None
            self.sliding_rate_limiter = None

        # security logging
        security_log_config = security_config.get('security_logging', {})
        if security_log_config.get('enabled', True):
            log_file = security_log_config.get('log_file', 'security.log')
            self.security_logger = SecurityLogger(log_file)
        else:
            self.security_logger = None

        self.logger.info("Security modules initialized")

    def authenticate(self) -> bool:
        """
        authenticate camera client

        returns:
            True if authentication successful
        """
        camera_id = self.config['camera_id']
        camera_role = self.config['camera_role']

        try:
            # generate jwt token
            self.token = self.auth_manager.generate_token(camera_id, camera_role)

            # validate token immediately
            payload = self.auth_manager.validate_token(self.token)

            if payload:
                if self.security_logger:
                    self.security_logger.log_auth_success(camera_id, camera_role)
                self.logger.info(f"Authentication successful for {camera_id}")
                return True
            else:
                if self.security_logger:
                    self.security_logger.log_auth_failure(camera_id, "token validation failed")
                self.logger.error("Authentication failed: invalid token")
                return False

        except Exception as e:
            if self.security_logger:
                self.security_logger.log_auth_failure(camera_id, str(e))
            self.logger.error(f"Authentication error: {e}")
            return False

    def check_permission(self, action: str) -> bool:
        """
        check if camera has permission for action

        args:
            action: action to check

        returns:
            True if authorized
        """
        camera_role = self.config['camera_role']

        if self.rbac_manager.validate_action(camera_role, action):
            self.logger.info(f"Permission granted for {action}")
            return True
        else:
            if self.security_logger:
                self.security_logger.log_unauthorized_access(
                    self.config['camera_id'],
                    action
                )
            self.logger.warning(f"Permission denied for {action}")
            return False

    def check_rate_limit(self) -> bool:
        """
        check if request is within rate limit

        returns:
            True if within limit
        """
        if not self.rate_limiter or not self.sliding_rate_limiter:
            return True

        camera_id = self.config['camera_id']

        # check both rate limiters
        token_bucket_ok = self.rate_limiter.allow_request(camera_id)
        sliding_window_ok = self.sliding_rate_limiter.allow_request(camera_id)

        if not token_bucket_ok or not sliding_window_ok:
            if self.security_logger:
                self.security_logger.log_rate_limit(camera_id, "api_request")
            self.logger.warning("Rate limit exceeded")
            return False

        return True

    def start_streaming(self):
        """start video streaming with security checks"""
        # check permission
        if not self.check_permission('start_streaming'):
            self.logger.error("Cannot start streaming: permission denied")
            return False

        # check rate limit
        if not self.check_rate_limit():
            self.logger.error("Cannot start streaming: rate limit exceeded")
            return False

        # initialize streaming client
        self.streaming_client = StreamingClient(self.config)

        # log connection attempt
        if self.security_logger:
            self.security_logger.log_connection(
                self.config['camera_id'],
                True,
                {"action": "start_streaming"}
            )

        # start streaming
        return self.streaming_client.run()

    def run(self):
        """run secure camera client"""
        # authenticate first
        if not self.authenticate():
            self.logger.error("Authentication failed, cannot proceed")
            return False

        # start streaming with security checks
        return self.start_streaming()


if __name__ == "__main__":
    client = SecureCameraClient()
    client.run()