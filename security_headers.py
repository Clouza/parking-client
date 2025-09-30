#!/usr/bin/env python3
"""
security headers configuration
adds security headers to http responses
"""

from typing import Dict

class SecurityHeaders:
    """security headers manager"""

    @staticmethod
    def get_secure_headers() -> Dict[str, str]:
        """
        get recommended security headers

        returns:
            dictionary of security headers
        """
        return {
            # prevent clickjacking
            'X-Frame-Options': 'DENY',

            # enable xss protection
            'X-XSS-Protection': '1; mode=block',

            # prevent mime sniffing
            'X-Content-Type-Options': 'nosniff',

            # force https
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',

            # referrer policy
            'Referrer-Policy': 'strict-origin-when-cross-origin',

            # content security policy
            'Content-Security-Policy': (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            ),

            # permissions policy
            'Permissions-Policy': (
                'geolocation=(), '
                'microphone=(), '
                'camera=(self)'
            )
        }

    @staticmethod
    def get_cors_headers(allowed_origin: str = "*") -> Dict[str, str]:
        """
        get cors headers

        args:
            allowed_origin: allowed origin for cors

        returns:
            dictionary of cors headers
        """
        return {
            'Access-Control-Allow-Origin': allowed_origin,
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Max-Age': '3600'
        }

    @staticmethod
    def get_cache_headers(cache_control: str = 'no-store') -> Dict[str, str]:
        """
        get cache control headers

        args:
            cache_control: cache control directive

        returns:
            dictionary of cache headers
        """
        return {
            'Cache-Control': cache_control,
            'Pragma': 'no-cache',
            'Expires': '0'
        }

    @classmethod
    def get_all_headers(cls, allowed_origin: str = "*") -> Dict[str, str]:
        """
        get all security headers combined

        args:
            allowed_origin: allowed origin for cors

        returns:
            dictionary of all headers
        """
        headers = {}
        headers.update(cls.get_secure_headers())
        headers.update(cls.get_cors_headers(allowed_origin))
        headers.update(cls.get_cache_headers())
        return headers