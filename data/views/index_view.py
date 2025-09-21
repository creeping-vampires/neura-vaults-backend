from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET

@require_GET
def index_view(request):
    """
    Root index page that provides links to API documentation and other resources
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nura Vault Backend</title>
        <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 0;
                color: #333;
                background-color: #f8f9fa;
            }
            .container {
                max-width: 1000px;
                margin: 0 auto;
                padding: 40px 20px;
            }
            header {
                text-align: center;
                margin-bottom: 40px;
            }
            h1 {
                color: #2c3e50;
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            .tagline {
                color: #7f8c8d;
                font-size: 1.2em;
                margin-bottom: 30px;
            }
            .card-container {
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                gap: 20px;
            }
            .card {
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                padding: 25px;
                flex: 1 1 300px;
                margin-bottom: 20px;
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }
            .card:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 20px rgba(0,0,0,0.1);
            }
            .card h2 {
                color: #3498db;
                margin-top: 0;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }
            .card ul {
                padding-left: 20px;
            }
            .card li {
                margin-bottom: 10px;
            }
            a {
                color: #3498db;
                text-decoration: none;
                font-weight: 500;
            }
            a:hover {
                text-decoration: underline;
            }
            footer {
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                color: #7f8c8d;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>Nura Vault Backend</h1>
                <p class="tagline">A robust Django-based backend service for DeFi yield optimization and allocation</p>
            </header>
            
            <div class="card-container">
                <div class="card">
                    <h2>API Documentation</h2>
                    <ul>
                        <li><a href="/api/docs/">Swagger UI</a> - Interactive API documentation</li>
                        <li><a href="/api/redoc/">ReDoc</a> - Alternative API documentation format</li>
                        <li><a href="/api/schema/">OpenAPI Schema</a> - Raw OpenAPI schema</li>
                        <li><a href="/api/documentation/">Documentation Index</a> - Documentation overview</li>
                    </ul>
                </div>
                
                <div class="card">
                    <h2>Key Endpoints</h2>
                    <ul>
                        <li><a href="/api/health/">Health Check</a> - System health status</li>
                        <li><a href="/api/vault/price/">Vault Price</a> - Latest vault price data</li>
                        <li><a href="/api/vault/price-chart/">Price Chart</a> - Historical price data</li>
                        <li><a href="/api/yield-monitor/status/">Yield Monitor</a> - Current yield status</li>
                    </ul>
                </div>
                
                <div class="card">
                    <h2>Resources</h2>
                    <ul>
                        <li><a href="/admin/">Admin Interface</a> - Django admin panel</li>
                        <li><a href="https://github.com/your-org/neura-vault-backend">GitHub Repository</a> - Source code</li>
                    </ul>
                </div>
            </div>
            
            <footer>
                <p>© 2025 Nura Vault - Optimizing DeFi Yield</p>
            </footer>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html_content, content_type='text/html')
