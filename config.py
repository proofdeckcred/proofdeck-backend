import os


SECRET_KEY = 'hbhfsgbhc67879732rgfguh378264idveydtc34'

# Database configuration
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'mysql+mysqlconnector://root@127.0.0.1/certifyme_db')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# JWT Configuration

JWT_SECRET_KEY = '648gcvwcvotya87476fvghcjasd82784'

VITE_CANVA_API_KEY='your_api_key_here'

# Canva API Configuration (NEW)
CANVA_CLIENT_ID = os.environ.get('CANVA_CLIENT_ID')
CANVA_CLIENT_SECRET = os.environ.get('CANVA_CLIENT_SECRET')