from django.http import HttpResponseNotFound
from django.shortcuts import redirect

def handler404(request, exception=None):
    """
    Custom 404 error handler that provides a user-friendly error page
    with links to documentation and API endpoints.
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nura Vault - Page Not Found</title>
        <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 0;
                color: #333;
                background-color: #f8f9fa;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                padding: 40px 20px;
                flex: 1;
            }
            header {
                text-align: center;
                margin-bottom: 40px;
            }
            h1 {
                color: #e74c3c;
                font-size: 3em;
                margin-bottom: 10px;
            }
            .error-code {
                font-size: 1.5em;
                color: #7f8c8d;
                margin-bottom: 30px;
            }
            .message {
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                padding: 25px;
                margin-bottom: 30px;
            }
            .suggestions {
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                padding: 25px;
            }
            h2 {
                color: #3498db;
                margin-top: 0;
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
                font-weight: 500;
            }
            a:hover {
                text-decoration: underline;
            }
            .home-button {
                display: inline-block;
                background-color: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                margin-top: 20px;
                text-decoration: none;
                transition: background-color 0.3s;
            }
            .home-button:hover {
                background-color: #2980b9;
                text-decoration: none;
            }
            footer {
                text-align: center;
                padding: 20px;
                background-color: #2c3e50;
                color: white;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>Page Not Found</h1>
                <div class="error-code">404 Error</div>
            </header>
            
            <div class="message">
                <h2>We couldn't find the page you were looking for</h2>
                <p>The page you requested does not exist or may have been moved. Please check the URL or try one of the suggestions below.</p>
                <a href="/" class="home-button">Go to Homepage</a>
            </div>
            
            <div class="suggestions">
                <h2>You might be looking for:</h2>
                <ul>
                    <li><a href="/api/docs/">API Documentation</a> - Interactive API documentation</li>
                    <li><a href="/api/health/">Health Check</a> - API health status</li>
                    <li><a href="/api/vault/price/">Vault Price</a> - Latest vault price data</li>
                    <li><a href="/api/yield-monitor/status/">Yield Monitor Status</a> - Current yield monitoring status</li>
                </ul>
            </div>
        </div>
        <footer>
            <p>© 2025 Nura Vault - Optimizing DeFi Yield</p>
        </footer>
    </body>
    </html>
    """
    return HttpResponseNotFound(html_content)
