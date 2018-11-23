FROM python:3.6

RUN apt-get update && apt-get install -y qpdf poppler-utils

# Install Python dependencies
RUN pip install pipenv

COPY Pipfile /code/
COPY Pipfile.lock /code/

WORKDIR /code

RUN cd /code/ && pipenv install -d

COPY . /code

ENV PYTHONPATH /code

# Run the green unicorn
CMD pipenv run python manage.py collectstatic --noinput && pipenv run gunicorn -w 4 -b 0.0.0.0:8040 --name offenegesetze_gunicorn \
  --log-level info --log-file /var/log/gunicorn.log offenegesetze.wsgi:application
