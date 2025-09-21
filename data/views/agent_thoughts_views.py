from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from data.models import AgnosticThought
from django.db.models import Q
from datetime import datetime, timedelta

@extend_schema(
    summary="Latest Agent Thoughts",
    description="""
    Fetch the latest agent thoughts from agent-agnostic mode with pagination and filtering options.
    
    This endpoint provides insight into the AI agents' decision-making process,
    showing their analysis, reasoning, and conclusions for yield optimization strategies.
    
    **Features:**
    - Agent-agnostic thoughts from agents running without specific database records
    - Pagination support with configurable page size
    - Time-based filtering (last N hours)
    - Agent role filtering
    - Summary statistics
    """,
    parameters=[
        OpenApiParameter(
            name='page',
            description='Page number for pagination',
            required=False,
            type=int,
            default=1
        ),
        OpenApiParameter(
            name='page_size',
            description='Number of thoughts per page (max 100)',
            required=False,
            type=int,
            default=20
        ),
        OpenApiParameter(
            name='agent_role',
            description='Filter by agent role (partial match)',
            required=False,
            type=str
        ),
        OpenApiParameter(
            name='hours',
            description='Show thoughts from last N hours',
            required=False,
            type=int,
            default=24
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Latest agent thoughts retrieved successfully",
            examples=[
                OpenApiExample(
                    'Success Response',
                    summary='Successful response with agnostic thoughts',
                    description='Returns paginated agent-agnostic thoughts with metadata',
                    value={
                        "results": [
                            {
                                "thoughtId": 3,
                                "agent_role": "Yield Allocation Executor",
                                "thought": "The current vault status indicates that there are no idle assets available...",
                                "createdAt": "2025-08-20T07:22:56.918720Z",
                                "formatted_time": "2 hours ago",
                                "execution_mode": "agent-agnostic"
                            }
                        ],
                        "pagination": {
                            "current_page": 1,
                            "total_pages": 1,
                            "total_thoughts": 3,
                            "page_size": 20,
                            "has_next": False,
                            "has_previous": False
                        },
                        "summary": {
                            "total_thoughts_in_period": 3,
                            "roles_active": ["Liquidity Pool Analyzer", "Yield Strategy QA Analyst", "Yield Allocation Executor"]
                        }
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Invalid pagination parameters")
    },
    tags=["Agent Intelligence"]
)
@api_view(['GET'])
@authentication_classes([])  # Public endpoint, no authentication required
@permission_classes([])      # Public endpoint, no permissions required
def get_latest_agent_thoughts(request):
    """
    Fetch the latest agent thoughts from agent-agnostic mode with pagination and filtering options.
    
    This endpoint provides insight into the AI agents' decision-making process,
    showing their analysis, reasoning, and conclusions for yield optimization strategies.
    """
    try:
        # Get query parameters
        page = request.GET.get('page', 1)
        page_size = min(int(request.GET.get('page_size', 20)), 100)  # Max 100 per page
        agent_role = request.GET.get('agent_role', None)
        hours = int(request.GET.get('hours', 24))
        
        # Calculate time filter
        time_threshold = timezone.now() - timedelta(hours=hours)
        
        # Debug: Print timezone info for troubleshooting
        print(f"DEBUG: Current time: {timezone.now()}")
        print(f"DEBUG: Time threshold: {time_threshold}")
        print(f"DEBUG: Hours filter: {hours}")
        
        # TEMPORARY: Test without time filter to bypass timezone issues
        if request.GET.get('no_filter') == 'true':
            print("DEBUG: Bypassing time filter for testing")
            queryset = AgnosticThought.objects.all().order_by('-createdAt')
        else:
            # Build queryset for agnostic thoughts only
            queryset = AgnosticThought.objects.filter(
                createdAt__gte=time_threshold
            ).order_by('-createdAt')
        
        # Debug: Print queryset info
        print(f"DEBUG: Total thoughts in DB: {AgnosticThought.objects.count()}")
        print(f"DEBUG: Thoughts after time filter: {queryset.count()}")
        if AgnosticThought.objects.exists():
            latest_thought = AgnosticThought.objects.order_by('-createdAt').first()
            print(f"DEBUG: Latest thought time: {latest_thought.createdAt}")
            print(f"DEBUG: Time difference: {timezone.now() - latest_thought.createdAt}")
        
        # Apply agent role filter if provided
        if agent_role:
            queryset = queryset.filter(agent_role__icontains=agent_role)
        
        # Get summary statistics
        total_thoughts_in_period = queryset.count()
        roles_active = list(queryset.values_list('agent_role', flat=True).distinct())
        
        # Paginate
        paginator = Paginator(queryset, page_size)
        
        try:
            thoughts_page = paginator.page(page)
        except PageNotAnInteger:
            thoughts_page = paginator.page(1)
        except EmptyPage:
            thoughts_page = paginator.page(paginator.num_pages)
        
        # Format results
        results = []
        for thought in thoughts_page:
            # Calculate relative time
            time_diff = timezone.now() - thought.createdAt
            if time_diff.days > 0:
                formatted_time = f"{time_diff.days} day{'s' if time_diff.days > 1 else ''} ago"
            elif time_diff.seconds > 3600:
                hours_ago = time_diff.seconds // 3600
                formatted_time = f"{hours_ago} hour{'s' if hours_ago > 1 else ''} ago"
            elif time_diff.seconds > 60:
                minutes_ago = time_diff.seconds // 60
                formatted_time = f"{minutes_ago} minute{'s' if minutes_ago > 1 else ''} ago"
            else:
                formatted_time = "Just now"
            
            results.append({
                'thoughtId': thought.thoughtId,
                'agent_role': thought.agent_role,
                'thought': thought.thought,
                'createdAt': thought.createdAt.isoformat(),
                'formatted_time': formatted_time,
                'execution_mode': thought.execution_mode,
                'crew_id': thought.crew_id
            })
        
        # Build response
        response_data = {
            'results': results,
            'pagination': {
                'current_page': thoughts_page.number,
                'total_pages': paginator.num_pages,
                'total_thoughts': paginator.count,
                'page_size': page_size,
                'has_next': thoughts_page.has_next(),
                'has_previous': thoughts_page.has_previous()
            },
            'filters': {
                'agent_role': agent_role,
                'hours': hours
            },
            'summary': {
                'total_thoughts_in_period': total_thoughts_in_period,
                'roles_active': roles_active
            }
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except ValueError as e:
        return Response(
            {'error': f'Invalid parameter value: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {'error': f'Internal server error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
