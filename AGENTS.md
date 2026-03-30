## Deploy Configuration (configured for Render)
- Platform: Render
- Production URL: https://onecation-sales-factory.onrender.com
- Deploy workflow: auto-deploy on push
- Deploy status command: HTTP health check
- Merge method: merge
- Project type: web app
- Post-deploy health check: https://onecation-sales-factory.onrender.com/

### Custom deploy hooks
- Pre-merge: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'` and `.\.venv\Scripts\python.exe -m compileall src tests web_dashboard.py`
- Deploy trigger: automatic on push to main
- Deploy status: poll production URL
- Health check: https://onecation-sales-factory.onrender.com/
