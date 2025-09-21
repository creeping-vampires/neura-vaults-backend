import logging
from django.http import JsonResponse
from django.conf import settings

logger = logging.getLogger(__name__)

# Removed WhitelistMiddleware as it's no longer needed
