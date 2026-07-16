import sys; sys.path.insert(0, '.')
from app.core.config import get_settings
print(get_settings().ADMIN_TOKEN)
