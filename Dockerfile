FROM python:3.11-slim-bullseye

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1

RUN apt -y update

RUN pip install "pipenv"

WORKDIR /app
COPY Pipfile ./
COPY Pipfile.lock ./
COPY main.py ./
COPY downloader/* ./downloader/

RUN pipenv install && pipenv run playwright install && pipenv run playwright install-deps

# Set this
ENV DISCORD_API_TOKEN ""
ENTRYPOINT ["pipenv", "run", "python", "main.py"]