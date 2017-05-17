from os import environ

get = environ.get

SECRET_KEY = get('SECRET_KEY', 'abcdefghijklmnop')
PLENARIO_SENTRY_URL = get('PLENARIO_SENTRY_URL', None)
DATA_DIR = '/tmp'

# Travis CI relies on the default values to build correctly,
# just keep in mind that if you push changes to the default
# values, you need to make sure to adjust for these changes 
# in the travis.yml
DB_USER = get('DB_USER', 'postgres')
DB_PASSWORD = get('DB_PASSWORD', 'password')
DB_HOST = get('DB_HOST', 'localhost')
DB_PORT = get('DB_PORT', 5432)
DB_NAME = get('DB_NAME', 'plenario_test')

RS_USER = get('RS_USER', 'postgres')
RS_PASSWORD = get('RS_PASSWORD', 'password')
RS_HOST = get('RS_HOST', 'localhost')
RS_PORT = get('RS_PORT', 5432)
RS_NAME = get('RS_NAME', 'plenario_test')

DATABASE_CONN = 'postgresql://{}:{}@{}:{}/{}'.\
    format(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME)
REDSHIFT_CONN = 'postgresql://{}:{}@{}:{}/{}'.\
    format(RS_USER, RS_PASSWORD, RS_HOST, RS_PORT, RS_NAME)

# Use this cache for data that can be refreshed
REDIS_HOST = get('REDIS_HOST', "localhost")

# See: https://pythonhosted.org/Flask-Cache/#configuring-flask-cache
# for config options
CACHE_CONFIG = {
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_KEY_PREFIX': get('CACHE_KEY_PREFIX', 'plenario_app')
}

# Load a default admin
DEFAULT_USER = {
    'name': get('DEFAULT_USER_NAME', 'Plenario Admin'),
    'email': get('DEFAULT_USER_EMAIL', 'plenario@email.com'),
    'password': get('DEFAULT_USER_PASSWORD', 'changemeplz')
}

# Amazon Web Services
AWS_ACCESS_KEY = get('AWS_ACCESS_KEY', '')
AWS_SECRET_KEY = get('AWS_SECRET_KEY', '')
AWS_REGION_NAME = get('AWS_REGION_NAME', 'us-east-1')
S3_BUCKET = get('S3_BUCKET', '')

# Email address for notifying site administrators
# Expect comma-delimited list of emails.
ADMIN_EMAILS = get('ADMIN_EMAILS').split(',') if get('ADMIN_EMAILS') else []

# For emailing users. ('MAIL_USERNAME' is an email address.)
MAIL_SERVER = get('MAIL_SERVER', 'smtp.gmail.com')
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_DISPLAY_NAME = 'Plenar.io Team'
MAIL_USERNAME = get('MAIL_USERNAME', '')
MAIL_PASSWORD = get('MAIL_PASSWORD', '')

# Toggle maintenence mode
MAINTENANCE = False

# Celery
CELERY_BROKER_URL = get("CELERY_BROKER_URL") or "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = get("CELERY_RESULT_BACKEND") or "db+" + DATABASE_CONN
FLOWER_URL = get("FLOWER_URL") or "http://localhost:5555"


class TestConfig:

    DB_NAME = 'test_plenario'
