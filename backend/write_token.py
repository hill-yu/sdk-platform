import sys; sys.path.insert(0, '.')
from app.core.config import get_settings
with open('token_tmp.txt', 'w') as f:
    f.write(get_settings().ADMIN_TOKEN)
