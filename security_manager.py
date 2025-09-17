#!/usr/bin/env python3
"""
Security Manager
API key authentication, HTTPS support, input validation, and security features
"""

import logging
import hashlib
import hmac
import base64
import ssl
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from urllib3.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re


class SecurityManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.security_config = config.get('security', {})

        # api key configuration
        self.api_key = self.security_config.get('api_key', '')
        self.api_secret = self.security_config.get('api_secret', '')

        # request limits
        self.rate_limit_requests = self.security_config.get('rate_limit_requests', 100)
        self.rate_limit_window = self.security_config.get('rate_limit_window', 60)
        self.request_history = []

        # input validation patterns
        self.validation_patterns = {
            'camera_id': re.compile(r'^[a-zA-Z0-9_-]{1,50}$'),
            'area_id': re.compile(r'^[a-zA-Z0-9_-]{1,20}$'),
            'command': re.compile(r'^[a-zA-Z0-9_]{1,30}$'),
            'filename': re.compile(r'^[a-zA-Z0-9._-]{1,100}$')
        }

    def setup_secure_session(self):
        """setup secure HTTP session with authentication and HTTPS"""
        session = requests.Session()

        # setup SSL context for HTTPS
        if self.security_config.get('use_https', True):
            session.verify = self.get_ssl_verify_path()

        # setup retry strategy
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST"],
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # add authentication headers
        session.headers.update(self.get_auth_headers())

        # add security headers
        session.headers.update({
            'User-Agent': f"ParkingCamera/{self.get_client_version()}",
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

        return session

    def get_ssl_verify_path(self):
        """get SSL certificate verification path"""
        cert_file = self.security_config.get('ssl_cert_file', '')
        if cert_file and Path(cert_file).exists():
            return cert_file
        elif self.security_config.get('ssl_verify', True):
            return True
        else:
            # development mode - disable SSL verification with warning
            self.logger.warning("SSL verification disabled - not recommended for production")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return False

    def get_auth_headers(self):
        """generate authentication headers"""
        headers = {}

        if self.api_key:
            headers['X-API-Key'] = self.api_key

        # add timestamp and signature for enhanced security
        if self.api_secret:
            timestamp = str(int(time.time()))
            signature = self.generate_signature(timestamp)
            headers['X-Timestamp'] = timestamp
            headers['X-Signature'] = signature

        return headers

    def generate_signature(self, timestamp, data=''):
        """generate HMAC signature for request authentication"""
        try:
            message = f"{timestamp}{data}".encode('utf-8')
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                message,
                hashlib.sha256
            ).hexdigest()
            return signature
        except Exception as e:
            self.logger.error(f"failed to generate signature: {e}")
            return ''

    def validate_request_data(self, data_type, value):
        """validate input data using predefined patterns"""
        try:
            if data_type not in self.validation_patterns:
                self.logger.warning(f"no validation pattern for data type: {data_type}")
                return True

            pattern = self.validation_patterns[data_type]
            is_valid = bool(pattern.match(str(value)))

            if not is_valid:
                self.logger.warning(f"invalid {data_type}: {value}")

            return is_valid

        except Exception as e:
            self.logger.error(f"validation error for {data_type}: {e}")
            return False

    def validate_payload(self, payload):
        """validate request payload structure and content"""
        try:
            if not isinstance(payload, dict):
                return False, "payload must be a dictionary"

            # validate common fields
            if 'camera_id' in payload:
                if not self.validate_request_data('camera_id', payload['camera_id']):
                    return False, "invalid camera_id format"

            if 'area_id' in payload:
                if not self.validate_request_data('area_id', payload['area_id']):
                    return False, "invalid area_id format"

            if 'command' in payload:
                if not self.validate_request_data('command', payload['command']):
                    return False, "invalid command format"

            # validate image data
            if 'image_data' in payload:
                if not self.validate_image_data(payload['image_data']):
                    return False, "invalid image data"

            # validate timestamp
            if 'timestamp' in payload:
                if not self.validate_timestamp(payload['timestamp']):
                    return False, "invalid timestamp"

            return True, "validation passed"

        except Exception as e:
            self.logger.error(f"payload validation error: {e}")
            return False, f"validation error: {str(e)}"

    def validate_image_data(self, image_data):
        """validate base64 image data"""
        try:
            if not isinstance(image_data, str):
                return False

            # check base64 format
            try:
                decoded = base64.b64decode(image_data)
            except Exception:
                return False

            # check image size limits
            max_size = self.security_config.get('max_image_size', 10 * 1024 * 1024)  # 10MB
            if len(decoded) > max_size:
                self.logger.warning(f"image data exceeds maximum size: {len(decoded)} bytes")
                return False

            # check for valid image headers
            image_headers = [
                b'\xff\xd8\xff',  # JPEG
                b'\x89PNG\r\n\x1a\n',  # PNG
                b'BM',  # BMP
            ]

            for header in image_headers:
                if decoded.startswith(header):
                    return True

            self.logger.warning("unknown image format detected")
            return False

        except Exception as e:
            self.logger.error(f"image validation error: {e}")
            return False

    def validate_timestamp(self, timestamp):
        """validate timestamp format and freshness"""
        try:
            # parse ISO timestamp
            ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

            # check timestamp freshness (within 5 minutes)
            now = datetime.now()
            if abs((now - ts.replace(tzinfo=None)).total_seconds()) > 300:
                self.logger.warning(f"timestamp too old or in future: {timestamp}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"timestamp validation error: {e}")
            return False

    def check_rate_limit(self):
        """check if current request exceeds rate limits"""
        try:
            current_time = time.time()

            # clean old requests from history
            self.request_history = [
                ts for ts in self.request_history
                if current_time - ts < self.rate_limit_window
            ]

            # check rate limit
            if len(self.request_history) >= self.rate_limit_requests:
                self.logger.warning("rate limit exceeded")
                return False

            # add current request
            self.request_history.append(current_time)
            return True

        except Exception as e:
            self.logger.error(f"rate limit check error: {e}")
            return True  # allow request on error

    def secure_request(self, method, url, **kwargs):
        """make secure HTTP request with authentication and validation"""
        try:
            # check rate limit
            if not self.check_rate_limit():
                raise requests.exceptions.RequestException("Rate limit exceeded")

            # validate payload if present
            if 'json' in kwargs:
                is_valid, message = self.validate_payload(kwargs['json'])
                if not is_valid:
                    raise requests.exceptions.RequestException(f"Payload validation failed: {message}")

            # setup secure session
            session = self.setup_secure_session()

            # add signature to payload if secret is configured
            if self.api_secret and 'json' in kwargs:
                timestamp = str(int(time.time()))
                data = json.dumps(kwargs['json'], sort_keys=True)
                signature = self.generate_signature(timestamp, data)
                kwargs['json']['_timestamp'] = timestamp
                kwargs['json']['_signature'] = signature

            # make request
            response = session.request(method, url, **kwargs)
            response.raise_for_status()

            return response

        except Exception as e:
            self.logger.error(f"secure request failed: {e}")
            raise

    def encrypt_sensitive_data(self, data):
        """encrypt sensitive data for storage"""
        try:
            from cryptography.fernet import Fernet

            key_file = Path(self.security_config.get('encryption_key_file', 'encryption.key'))

            if not key_file.exists():
                # generate new key
                key = Fernet.generate_key()
                key_file.write_bytes(key)
                self.logger.info("generated new encryption key")
            else:
                key = key_file.read_bytes()

            fernet = Fernet(key)
            encrypted_data = fernet.encrypt(data.encode('utf-8'))
            return base64.b64encode(encrypted_data).decode('utf-8')

        except ImportError:
            self.logger.warning("cryptography library not available, storing data in plain text")
            return base64.b64encode(data.encode('utf-8')).decode('utf-8')
        except Exception as e:
            self.logger.error(f"encryption error: {e}")
            return base64.b64encode(data.encode('utf-8')).decode('utf-8')

    def decrypt_sensitive_data(self, encrypted_data):
        """decrypt sensitive data from storage"""
        try:
            from cryptography.fernet import Fernet

            key_file = Path(self.security_config.get('encryption_key_file', 'encryption.key'))

            if not key_file.exists():
                raise Exception("encryption key not found")

            key = key_file.read_bytes()
            fernet = Fernet(key)

            decoded_data = base64.b64decode(encrypted_data.encode('utf-8'))
            decrypted_data = fernet.decrypt(decoded_data)
            return decrypted_data.decode('utf-8')

        except ImportError:
            # fallback to base64 decoding
            return base64.b64decode(encrypted_data.encode('utf-8')).decode('utf-8')
        except Exception as e:
            self.logger.error(f"decryption error: {e}")
            return base64.b64decode(encrypted_data.encode('utf-8')).decode('utf-8')

    def get_client_version(self):
        """get client version for user agent"""
        try:
            version_file = Path('VERSION')
            if version_file.exists():
                return version_file.read_text().strip()
            return '1.0.0'
        except Exception:
            return '1.0.0'

    def sanitize_filename(self, filename):
        """sanitize filename for safe file operations"""
        try:
            # remove path separators and dangerous characters
            sanitized = re.sub(r'[^\w\-_\.]', '_', filename)

            # limit length
            if len(sanitized) > 100:
                name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
                sanitized = name[:95] + ('.' + ext if ext else '')

            # ensure it's not empty
            if not sanitized:
                sanitized = 'unknown_file'

            return sanitized

        except Exception as e:
            self.logger.error(f"filename sanitization error: {e}")
            return 'unknown_file'

    def audit_log(self, action, details=None):
        """log security-relevant actions for auditing"""
        try:
            audit_entry = {
                'timestamp': datetime.now().isoformat(),
                'action': action,
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'details': details or {}
            }

            # write to audit log
            audit_file = Path(self.security_config.get('audit_log_file', 'security_audit.log'))
            with open(audit_file, 'a') as f:
                f.write(json.dumps(audit_entry) + '\n')

        except Exception as e:
            self.logger.error(f"audit logging error: {e}")

    def get_security_status(self):
        """get current security configuration status"""
        return {
            'api_key_configured': bool(self.api_key),
            'api_secret_configured': bool(self.api_secret),
            'https_enabled': self.security_config.get('use_https', True),
            'ssl_verification': self.security_config.get('ssl_verify', True),
            'rate_limit_active': bool(self.rate_limit_requests),
            'encryption_available': Path(self.security_config.get('encryption_key_file', 'encryption.key')).exists(),
            'request_count': len(self.request_history)
        }