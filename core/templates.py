# core/templates.py
from fastapi.templating import Jinja2Templates

# Create a single instance to be imported by other files
templates = Jinja2Templates(directory="templates")