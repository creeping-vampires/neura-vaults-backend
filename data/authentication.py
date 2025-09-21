from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
from django.core.cache import cache
import jwt
import requests
import logging

logger = logging.getLogger(__name__)

class PrivyAuthenticationError(AuthenticationFailed):
    """Custom exception for Privy authentication errors."""
    pass

class PrivyAuthentication(BaseAuthentication):
    """
    Custom authentication class for Privy JWT tokens.
    Extracts the wallet address from the verified JWT token.
    """
    
    # Cache key for the JWKS
    JWKS_CACHE_KEY = 'privy_jwks'
    # Cache the JWKS for 24 hours (adjust as needed)
    JWKS_CACHE_TTL = 60 * 60 * 24
    
    def get_jwks(self):
        """
        Get Privy's JWKS (JSON Web Key Set) from cache or fetch from API
        """
        # Try to get JWKS from cache
        jwks = cache.get(self.JWKS_CACHE_KEY)
        if jwks:
            return jwks
            
        # If not in cache, fetch from Privy API
        try:
            jwks_url = f"{settings.PRIVY_API_URL}/apps/{settings.PRIVY_APP_ID}/jwks.json"
            logger.info(f"Fetching JWKS from: {jwks_url}")
            jwks_response = requests.get(jwks_url, timeout=5)
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
            
            # Cache the JWKS
            cache.set(self.JWKS_CACHE_KEY, jwks, self.JWKS_CACHE_TTL)
            return jwks
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch JWKS: {str(e)}")
            raise AuthenticationFailed('Authentication service unavailable')
    
    def authenticate(self, request):
        # Get the auth header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return None

        try:
            # Extract the token
            if not auth_header.startswith('Bearer '):
                raise AuthenticationFailed('Invalid authorization header format')
            
            token = auth_header.split(' ')[1]
            
            # Verify and decode the token
            try:
                # Get Privy's JWKS
                jwks = self.get_jwks()
                
                # Find the key used to sign the token
                header = jwt.get_unverified_header(token)
                key = None
                for jwk in jwks['keys']:
                    if jwk['kid'] == header['kid']:
                        # Use the correct algorithm based on the key type
                        if jwk.get('kty') == 'EC':
                            key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
                        elif jwk.get('kty') == 'RSA':
                            key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                        else:
                            logger.warning(f"Unsupported key type: {jwk.get('kty')}")
                        break
                
                if not key:
                    # If key not found, try refreshing the JWKS once
                    cache.delete(self.JWKS_CACHE_KEY)
                    jwks = self.get_jwks()
                    
                    for jwk in jwks['keys']:
                        if jwk['kid'] == header['kid']:
                            if jwk.get('kty') == 'EC':
                                key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
                            elif jwk.get('kty') == 'RSA':
                                key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                            break
                            
                    if not key:
                        raise AuthenticationFailed('No matching key found')
                
                # Get the algorithm from the token header
                alg = header.get('alg', 'ES256')
                
                # Verify and decode the token
                payload = jwt.decode(
                    token,
                    key=key,
                    algorithms=[alg],  # Use the algorithm from the token header
                    audience=settings.PRIVY_APP_ID if hasattr(settings, 'PRIVY_APP_ID') else None,
                    options={'verify_exp': False}  # Disable expiration check for now
                )
                
                # Extract privy address from the 'sub' field
                privy_address = payload.get('sub')
                if not privy_address:
                    raise AuthenticationFailed('No verified privy address found in token')
                
                # Create a PrivyUser object instead of returning just the string
                from .views import PrivyUser
                privy_user = PrivyUser(privy_address)
                logger.info(f"Successfully authenticated privy: {privy_address}")
                return (privy_user, None)
                
            except Exception as e:
                error_message = str(e)
                if 'expired' in error_message.lower():
                    logger.error("Token has expired")
                    raise AuthenticationFailed('Token has expired')
                elif 'audience' in error_message.lower():
                    logger.error("Token has invalid audience")
                    raise AuthenticationFailed('Token has invalid audience')
                else:
                    logger.error(f"Invalid token: {error_message}")
                    raise AuthenticationFailed('Invalid token')
            except requests.RequestException as e:
                logger.error(f"Failed to fetch JWKS: {str(e)}")
                raise AuthenticationFailed('Authentication service unavailable')
                
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise AuthenticationFailed(str(e))

    def authenticate_header(self, request):
        return 'Bearer' 