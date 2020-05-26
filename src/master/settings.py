"""
Django settings for master project.

Generated by 'django-admin startproject' using Django 2.0.7.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "g+g1=lxqwg1#2)#su3)pulz4(dl2jf!5l9d3pn=w+3puk5o(+2"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "constance",
    "constance.backends.database",
    "rest_framework",
    "django_rq",
    "scheduler",
    "main",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # 'master.middleware.FirstVisitMiddleware'
]

ROOT_URLCONF = "master.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "master.wsgi.application"

# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

# Rest Framework
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
        "api.renderers.BinaryFileRenderer",
    )
}

# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa E501
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator", },
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator", },
]

# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = "/app/static"

# Constance settings config
CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_CONFIG = {"FIRST_TIME": (True, "Whether to execute first time setup wizard")}

RQ_QUEUES = {
    "default": {"HOST": "localhost", "PORT": 6379, "DB": 0, "DEFAULT_TIMEOUT": 360, },
    "high": {"HOST": "localhost", "PORT": 6379, "DB": 0, "DEFAULT_TIMEOUT": 360, },
}

FIXTURE_DIRS = ("api/fixtures/",)

# available backends
MLBENCH_BACKENDS = ["MPI", "GLOO", "NCCL"]

MPI_COMMAND = "/.openmpi/bin/mpirun --mca btl_tcp_if_exclude docker0,lo"\
              " -x KUBERNETES_SERVICE_HOST -x KUBERNETES_SERVICE_PORT "\
              "-x LD_LIBRARY_PATH=/usr/local/nvidia/lib64 --host {hosts} "

# available images. [("Name", "image", "command", gpu-supported)]
MLBENCH_IMAGES = {
    "mlbench/pytorch-cifar10-resnet:latest": (
        "PyTorch Cifar-10 ResNet-20",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        True,
    ),
    "mlbench/pytorch-cifar10-resnet-scaling:latest": (
        "PyTorch Cifar-10 ResNet-20 (Scaling LR)",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        True,
    ),
    "mlbench/pytorch-epsilon-logistic-regression-all-reduce:latest": (
        "PyTorch Linear Logistic Regression",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        True,
    ),
    "mlbench/pytorch-wmt14-gnmt-all-reduce:latest": (
        "PyTorch Machine Translation GNMT",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        True,
    ),
    "mlbench/pytorch-wmt17-transformer-all-reduce:latest": (
        "PyTorch Machine Translation Transformer",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        True,
    ),
    "mlbench/tensorflow-cifar10-resnet:latest": (
        "Tensorflow Cifar-10 ResNet-20",
        "/conda/bin/python /codes/main.py --run_id {run_id} --rank {rank} --hosts {hosts} --backend {backend}",
        False,
    ),
}
