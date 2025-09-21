from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET

@require_GET
def api_docs_redirect(request):
    """
    Simple view to redirect users to the API documentation.
    This handles the case where users might be looking for /api/docs
    """
    return redirect('/api/docs/')

@require_GET
def api_docs_index(request):
    """
    Simple HTML page that serves as an index for API documentation
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nura Vault API Documentation</title>
        <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
        <style>
            body {
                font-family: Arial, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 20px;
                color: #333;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f9f9f9;
                border-radius: 5px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #2c3e50;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }
            ul {
                padding-left: 20px;
            }
            li {
                margin-bottom: 10px;
            }
            a {
                color: #3498db;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Nura Vault API Documentation</h1>
            <p>Welcome to the Nura Vault API documentation. Please select one of the following documentation formats:</p>
            <ul>
                <li><a href="/api/docs/">Swagger UI</a> - Interactive API documentation</li>
                <li><a href="/api/redoc/">ReDoc</a> - Alternative API documentation format</li>
                <li><a href="/api/schema/">OpenAPI Schema</a> - Raw OpenAPI schema</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html_content, content_type='text/html')
